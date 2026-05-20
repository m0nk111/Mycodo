#!/opt/Mycodo/env/bin/python3
# coding=utf-8
"""
telegram_grow_bot.py — Standalone Telegram ↔ LLM chat bot for the grow system.

Runs as a systemd service. Polls Telegram for messages, reads current sensor
data from InfluxDB (via Mycodo's utils), sends queries to Guardian LLM with
full system context, and replies back in Telegram.

Commands:
  /status  — Current sensor snapshot (no LLM)
  /advies  — Ask LLM for dosing advice (dry run)
  /reset   — Clear conversation history
  Any other text → free-form chat with the grow advisor LLM

Deploy:
  sudo cp telegram-grow-bot.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now telegram-grow-bot.service

Requires: Mycodo Python env (/opt/Mycodo/env) for InfluxDB access
"""

import base64
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Add Mycodo to path for influx utils
sys.path.insert(0, '/opt/Mycodo')

import requests
from mycodo.utils.influx import read_influxdb_single, query_flux

# ── Configuration ─────────────────────────────────────────────────────────────

# Mycodo DB for dosing history and runtime credential fallback
MYCODO_DB = "/opt/Mycodo/databases/mycodo.db"
REGULATOR_UID = "1b2777f0-e3e5-4ec8-adfb-bcd045e95f42"


def _read_regulator_custom_options() -> dict:
    """Read regulator custom_options for runtime credential fallback."""
    conn = None
    try:
        conn = sqlite3.connect(MYCODO_DB)
        row = conn.execute(
            "SELECT custom_options FROM custom_controller WHERE unique_id = ?",
            (REGULATOR_UID,)
        ).fetchone()
        if not row or not row[0]:
            return {}
        return json.loads(row[0])
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()


def _env_or_db(env_name: str, db_key: str, default: str = "") -> str:
    """Resolve configuration from env first, then regulator custom options."""
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    db_value = REGULATOR_CUSTOM_OPTIONS.get(db_key)
    if db_value in (None, ""):
        return default
    return str(db_value)


def _env_or_default(env_name: str, default: str = "") -> str:
    """Resolve configuration from environment with an optional default."""
    value = os.getenv(env_name, "").strip()
    return value or default


def _camera_auth_from_env() -> tuple[str, str] | None:
    """Return optional camera basic auth from environment variables."""
    username = os.getenv("TG_GROW_BOT_CAMERA_USER", "").strip()
    password = os.getenv("TG_GROW_BOT_CAMERA_PASSWORD", "").strip()
    if not username or not password:
        return None
    return username, password


REGULATOR_CUSTOM_OPTIONS = _read_regulator_custom_options()

TELEGRAM_BOT_TOKEN = _env_or_db(
    "TG_GROW_BOT_TELEGRAM_BOT_TOKEN",
    "telegram_bot_token"
)
TELEGRAM_CHAT_ID = _env_or_db(
    "TG_GROW_BOT_TELEGRAM_CHAT_ID",
    "telegram_chat_id"
)

LLM_API_URL = _env_or_default(
    "TG_GROW_BOT_LLM_API_URL",
    "http://192.168.1.35:11434/v1/chat/completions"
)
LLM_API_KEY = _env_or_db(
    "TG_GROW_BOT_LLM_API_KEY",
    "advisor_api_key"
)
LLM_MODEL = "Huihui-gemma-4-26B-A4B-it-abliterated"
VISION_MODEL = "Huihui-gemma-4-26B-A4B-it-abliterated"
EXTRACT_MODEL = "Huihui-gemma-4-26B-A4B-it-abliterated"
VISION_UNSUPPORTED_ERROR_FRAGMENT = "image input is not supported"
VISION_UNSUPPORTED_USER_MESSAGE = (
    "⚠️ Beeldanalyse is nu niet beschikbaar. Guardian accepteert momenteel geen "
    "afbeeldingen voor het vision-pad (mmproj / multimodal config ontbreekt). "
    "Tekstchat werkt wel, maar /foto en /wortel nu niet."
)

GUARDIAN_QUEUE_STATUS_URL = "http://192.168.1.35:11434/v1/queue/status"
GUARDIAN_ADMIN_LOAD_URL = "http://192.168.1.35:11434/admin/load"
GUARDIAN_DEFAULT_TIMEOUT = 600
GUARDIAN_RECOVER_503_RETRIES = 1
GUARDIAN_RECOVER_RETRY_DELAY_S = 2

# Camera
CAMERA_SNAPSHOT_URL = _env_or_default(
    "TG_GROW_BOT_CAMERA_URL",
    "http://192.168.1.203/image.jpg"
)
CAMERA_AUTH = _camera_auth_from_env()

# Bot memory DB
BOT_MEMORY_DB = "/home/flip/mycodo-config-private/data/grow_bot_memory.db"
GROW_LOG_PATH = Path("/home/flip/mycodo-config-private/notes/GROW_LOG.md")
GROW_LOG_CHECK_SECTION = "## Telegram Bot Check Log"
GROW_LOG_CHECK_HEADER = (
    f"\n{GROW_LOG_CHECK_SECTION}\n\n"
    "| Timestamp | Check | Summary |\n"
    "|---|---|---|\n"
)

# Sensor config: (device_id, unit, channel, measure, max_age_sec)
SENSOR_CONFIG = {
    'ph':     ('97f9e370-d63b-43c5-82fd-fb0c407b687e', 'pH',    0, None,           300),
    'ec':     ('97f9e370-d63b-43c5-82fd-fb0c407b687e', 'uS_cm', 1, None,           300),
    'volume': ('be6eb429-9777-4900-8fb3-fc75d0602452', 'l',     2, 'volume',       300),
    'flow':   ('c36117b9-5835-40ba-b93e-275a3ae645ca', 'l_min', 0, 'rate_volume',  120),
}

# Grow config
# Track grow day/week from the date the current plant entered the NFT gutter.
GROW_START_DATE = "2026-05-16"
CURRENT_RUN_CONTEXT_TS = f"{GROW_START_DATE}T00:00:00"

POLL_INTERVAL = 2  # seconds between Telegram getUpdates calls
MAX_HISTORY = 20   # max conversation messages to keep in context
LAST_VISION_ERROR: str | None = None

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("telegram_grow_bot")


def _validate_runtime_config() -> None:
    """Fail fast on missing required config and warn about optional pieces."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TG_GROW_BOT_TELEGRAM_BOT_TOKEN or regulator custom_options.telegram_bot_token")
    if not TELEGRAM_CHAT_ID:
        missing.append("TG_GROW_BOT_TELEGRAM_CHAT_ID or regulator custom_options.telegram_chat_id")
    if missing:
        raise RuntimeError("Missing required bot config: " + "; ".join(missing))
    if not LLM_API_KEY:
        log.warning(
            "Guardian API key not configured; LLM requests will be sent without an Authorization header"
        )
    if CAMERA_AUTH is None:
        log.warning(
            "Camera auth is not configured via env; /foto and /wortel may fail if the camera requires basic auth"
        )

# ── System Lore ───────────────────────────────────────────────────────────────

SYSTEM_LORE = """
## Systeem Overzicht
Je bent de AI assistent voor een geautomatiseerd NFT (Nutrient Film Technique) hydroponisch cannabis systeem.
De gebruiker praat met je via Telegram. Je bent vriendelijk, direct, en antwoordt in het Nederlands.

### Fysiek
- 1 plant in een 160cm NFT goot, in een 80×40×80cm growkast
- 50L HDPE reservoir (Sterk Tura 2), werkbereik 25-37L
- Eheim CompactON 2100 circulatiepomp (2.0m opvoerhoogte, 22W)
- SunSun AUV-06B UV-C lamp in reservoir (bacteriële controle)
- Spider Farmer SF1000 LED (Samsung LM301H EVO), 40cm van canopy, 100%
- YF-S401 Hall flow sensor (GPIO 26, 5880 pulses/L)

### Sensoren
- pH: DFRobot SEN0169-V2 via DFR0504 isolator → ADS1115 CH0
- EC: DFRobot DFR0300 (K=1) via DFR0504 isolator → ADS1115 CH1
- Waterpeil: QDY30A analoog → ADS1115 CH2 (volume in liters)
- Watertemperatuur: DS18B20 (1-Wire GPIO 23)
- Omgeving: DHT22 (GPIO 18, temp + RV)
- Backup level: 2× XKC-Y25-NPN (GPIO 22=laag/15L, GPIO 27=hoog/40L)

### Doseerpomp Mapping (8× NKP-DC-S06B peristaltisch, HW-283 relay, Active LOW)
| Pomp | Product | ml/min |
|------|---------|--------|
| 1 | Sensi A (EC regulatie) | 47.4 |
| 2 | Sensi B (EC regulatie) | 48.0 |
| 3 | B-52 (vitamine boost) | 48.0 |
| 4 | Voodoo Juice (rhizobacteriën) | 48.0 |
| 5 | Big Bud (bloom booster) | 48.0 |
| 6 | Bud Candy (suikers, bloom) | 48.0 |
| 7 | Overdrive (late bloom finisher) | 48.0 |
| 8 | pH Down (CANNA pH- Blüte PRO, 59% H3PO4, verdund 1:5) | 47.0 |

### Nutriëntenschema (AN Sensi Grow, ml/L/week — /7 voor dagelijks)
Week 1-2: B-52 2.0, Voodoo Juice 2.0
Week 3-4: B-52 2.0
Week 5+: alleen basis A+B (EC regulatie)
Bloom pompen (5-7) pas bij bloei.

### Water
- Vulwater: RO (osmosewater), ~0 µS/cm
- pH Down: CANNA pH- Blüte PRO 59% H3PO4, verdund 1:5 voor veiligheid
- pH Perfect: AN Sensi A+B buffert pH automatisch — pH Down alleen bij > setpoint

### Grow Geschiedenis
- Run #1: MISLUKT door wortelrot (aquaponics, wortels nooit getrimd, lage flow)
- Plant v2: gestorven door geen waterflow
- Zaad v3: wilde niet goed ontspruiten
- Geleerd: NFT wortels MOETEN geïnspecteerd/getrimd worden, steenwol = te nat
- Huidige run: zaad/plant v4 in pure hydroponics met hydroton, UV-C, schoon systeem
- In NFT goot geplaatst: 2026-05-16
- pH crisis 2026-03-24: pH crashte naar 3.41 door ongecontroleerde A+B dosering

### Veiligheidssysteem
- pH danger guard: blokkeert ALLE dosering bij pH < 4.0 of pH > 8.0
- Daily dose limits: pH Down max 25ml/dag, EC A+B max 100ml/dag elk
- Flow check: weigert dosering als circulatiepomp niet draait
- EC safety thresholds komen live uit de actieve Mycodo regulatorconfig hieronder
- Overdose guard: max 1.5× geplande dagdosis per pomp
- Waterpeil guard: blokkeert alle dosering bij laag water

### NFT Flow Onderzoek
- Cannabis NFT optimaal: 0.3-0.5 L/min (Al-Tawaha 2018, Genuncio 2012)
- Intermittent flow kan beter zijn: 5 min aan / 25 min uit (Subah 2025)
- Hydroponics beter dan aquaponics voor bloei: 42-116% meer bloemmassa (Yep 2020)
- Recirculatie > run-to-waste: 182% meer THC (Velechovský 2024)

### Jouw Rol
- Je bent een ervaren hydroponic cannabis groeiadviseur
- Antwoord altijd in het Nederlands
- Wees direct en praktisch — geen academische essays
- Bij vragen over dosering: wees CONSERVATIEF, liever te weinig dan te veel
- Je hebt toegang tot live sensordata — gebruik die in je antwoorden
- Als iets buiten je kennis valt, zeg dat eerlijk
- Max 3-4 alinea's per antwoord tenzij expliciet meer gevraagd
""".strip()

# ── Sensor Reading (via Mycodo InfluxDB) ──────────────────────────────────────


def _read_sensor(name: str) -> float | None:
    """Read a sensor value using Mycodo's read_influxdb_single."""
    cfg = SENSOR_CONFIG.get(name)
    if not cfg:
        return None
    dev_id, unit, channel, measure, max_age = cfg
    try:
        kwargs = {'value': 'LAST', 'duration_sec': max_age}
        if measure:
            kwargs['measure'] = measure
        ts, val = read_influxdb_single(dev_id, unit, channel, **kwargs)
        return float(val) if val is not None else None
    except Exception as e:
        log.warning("Sensor read error (%s): %s", name, e)
        return None


def read_sensors() -> dict:
    """Read all sensors and return a dict with current values."""
    data = {}
    for name in SENSOR_CONFIG:
        data[name] = _read_sensor(name)
    # Grow info
    try:
        start = date.fromisoformat(GROW_START_DATE)
        day_num = max(1, (date.today() - start).days + 1)
        week = max(1, (day_num - 1) // 7 + 1)
    except Exception:
        day_num, week = 1, 1
    data['grow_day'] = day_num
    data['grow_week'] = week
    if day_num < 14:
        data['phase'] = 'zaailing'
    elif day_num < 42:
        data['phase'] = 'vegetatief'
    elif day_num < 56:
        data['phase'] = 'vroege bloei'
    else:
        data['phase'] = 'bloei'
    return data


def format_status(data: dict) -> str:
    """Format sensor data as a human-readable status message."""
    ph = data.get('ph')
    ec = data.get('ec')
    vol = data.get('volume')
    flow = data.get('flow')
    lines = [
        f"📊 *Sensor Status* ({datetime.now().strftime('%H:%M')})",
        f"",
        f"🌱 Grow dag {data.get('grow_day', '?')} (week {data.get('grow_week', '?')}) — {data.get('phase', '?')}",
        f"",
        f"pH: {ph:.2f}" if ph is not None else "pH: geen data",
        f"EC: {ec:.0f} µS/cm" if ec is not None else "EC: geen data",
        f"Waterpeil: {vol:.1f} L" if vol is not None else "Waterpeil: geen data",
        f"Flow: {flow:.3f} L/min" if flow is not None else "Flow: geen data",
    ]

    # Add dosing history
    dosed = read_dosing_today()
    if dosed:
        lines.append("")
        lines.append("💉 *Vandaag gedoseerd:*")
        lines.append(f"  pH Down: {dosed.get('ph_ml', 0):.1f} ml")
        lines.append(f"  EC A: {dosed.get('ec_a_ml', 0):.1f} ml")
        lines.append(f"  EC B: {dosed.get('ec_b_ml', 0):.1f} ml")

    # Add trends
    trends = read_trends()
    if trends:
        lines.append("")
        lines.append("📈 *Trend (6u):*")
        for name, vals in trends.items():
            if vals and len(vals) >= 2:
                delta = vals[-1] - vals[0]
                arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
                lines.append(f"  {name}: {arrow} {delta:+.1f}")

    return "\n".join(lines)


def _sanitize_grow_log_summary(text: str, limit: int = 240) -> str:
    """Collapse whitespace and escape markdown table separators for log rows."""
    collapsed = re.sub(r'\s+', ' ', (text or '').strip()).replace('|', '/')
    if not collapsed:
        return '-'
    if len(collapsed) > limit:
        return collapsed[:limit - 3].rstrip() + '...'
    return collapsed


def _status_summary(data: dict) -> str:
    """Generate a concise one-line summary for grow-log check entries."""
    parts = [
        f"dag {data.get('grow_day', '?')}",
        f"week {data.get('grow_week', '?')}",
        data.get('phase', '?'),
    ]
    ph = data.get('ph')
    ec = data.get('ec')
    vol = data.get('volume')
    flow = data.get('flow')
    if ph is not None:
        parts.append(f"pH {ph:.2f}")
    if ec is not None:
        parts.append(f"EC {ec:.0f} µS/cm")
    if vol is not None:
        parts.append(f"vol {vol:.1f} L")
    if flow is not None:
        parts.append(f"flow {flow:.3f} L/min")
    return '; '.join(parts)


def _trend_summary(trends: dict) -> str:
    """Generate a concise one-line trend summary for grow-log check entries."""
    parts = []
    for name, vals in trends.items():
        if vals and len(vals) >= 2:
            delta = vals[-1] - vals[0]
            parts.append(f"{name} {vals[0]:.1f}->{vals[-1]:.1f} ({delta:+.1f})")
    return '; '.join(parts) if parts else 'Geen trend data beschikbaar.'


def append_grow_log_check(check_name: str, summary: str):
    """Append a timestamped bot-check row to the shared grow log."""
    try:
        if not GROW_LOG_PATH.exists():
            log.warning("[GROW_LOG] Path not found: %s", GROW_LOG_PATH)
            return

        row = (
            f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
            f"{_sanitize_grow_log_summary(check_name, limit=40)} | "
            f"{_sanitize_grow_log_summary(summary)} |\n"
        )
        text = GROW_LOG_PATH.read_text(encoding='utf-8')

        if GROW_LOG_CHECK_SECTION not in text:
            if not text.endswith('\n'):
                text += '\n'
            text += GROW_LOG_CHECK_HEADER + row
        else:
            section_start = text.index(GROW_LOG_CHECK_SECTION)
            next_header = text.find('\n## ', section_start + len(GROW_LOG_CHECK_SECTION))
            if next_header == -1:
                if not text.endswith('\n'):
                    text += '\n'
                text += row
            else:
                text = text[:next_header] + row + text[next_header:]

        GROW_LOG_PATH.write_text(text, encoding='utf-8')
        log.info("[GROW_LOG] Logged check: %s", check_name)
    except Exception as e:
        log.warning("[GROW_LOG] Failed to append %s: %s", check_name, e)


# ── Dosing History ────────────────────────────────────────────────────────────


def read_dosing_today() -> dict | None:
    """Read today's dosing totals from regulator's DB state."""
    try:
        conn = sqlite3.connect(MYCODO_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT custom_options FROM custom_controller WHERE unique_id=?",
            (REGULATOR_UID,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        data = json.loads(row[0])
        daily = data.get('daily_dosed')
        if daily:
            if isinstance(daily, str):
                daily = json.loads(daily)
            if daily.get('date') == date.today().isoformat():
                return daily
        return {'ph_ml': 0, 'ec_a_ml': 0, 'ec_b_ml': 0}
    except Exception as e:
        log.warning("Dosing history read error: %s", e)
        return None


def read_regulator_config() -> dict | None:
    """Read live EC-related regulator thresholds from Mycodo's DB state."""
    try:
        conn = sqlite3.connect(MYCODO_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT name, device, custom_options FROM custom_controller WHERE unique_id=?",
            (REGULATOR_UID,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None

        options = json.loads(row[2]) if row[2] else {}

        def _num(value):
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        def _bool(value, default: bool = False) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ('1', 'true', 'yes', 'on')
            return bool(value)

        setpoint_ec = _num(options.get('setpoint_ec'))
        hysteresis_ec = _num(options.get('hysteresis_ec'))
        ec_high_threshold = _num(options.get('ec_high_threshold'))
        max_ec_before_dose = _num(options.get('max_ec_before_dose'))

        grow_start = options.get('grow_start_date') or GROW_START_DATE
        try:
            grow_week = max(1, ((date.today() - date.fromisoformat(grow_start)).days // 7) + 1)
        except Exception:
            grow_start = GROW_START_DATE
            grow_week = max(1, ((date.today() - date.fromisoformat(grow_start)).days // 7) + 1)

        ec_age_coupling_enabled = _bool(options.get('ec_age_coupling_enabled'), True)
        ec_age_pct = {
            1: _num(options.get('ec_week1_pct')) or 35.0,
            2: _num(options.get('ec_week2_pct')) or 50.0,
            3: _num(options.get('ec_week3_pct')) or 65.0,
            4: _num(options.get('ec_week4_pct')) or 80.0,
        }.get(grow_week, 100.0)
        if not ec_age_coupling_enabled:
            ec_age_pct = 100.0

        effective_setpoint_ec = setpoint_ec
        effective_hysteresis_ec = hysteresis_ec
        range_ec_low = None
        range_ec_high = None
        if setpoint_ec is not None and hysteresis_ec is not None:
            factor = max(0.0, ec_age_pct) / 100.0
            effective_setpoint_ec = max(0.0, setpoint_ec * factor)
            if factor >= 1.0:
                effective_hysteresis_ec = hysteresis_ec
            else:
                effective_hysteresis_ec = max(25.0, hysteresis_ec * factor)
            range_ec_low = max(0.0, effective_setpoint_ec - effective_hysteresis_ec)
            range_ec_high = effective_setpoint_ec + effective_hysteresis_ec

        effective_max_ec_before_dose = max_ec_before_dose
        if max_ec_before_dose is not None and range_ec_high is not None:
            effective_max_ec_before_dose = min(max_ec_before_dose, range_ec_high)

        effective_ec_high_threshold = ec_high_threshold
        if ec_high_threshold is not None and range_ec_high is not None and effective_hysteresis_ec is not None:
            effective_ec_high_threshold = min(
                ec_high_threshold,
                range_ec_high + effective_hysteresis_ec,
            )

        return {
            'name': row[0],
            'device': row[1],
            'setpoint_ec': setpoint_ec,
            'hysteresis_ec': hysteresis_ec,
            'effective_setpoint_ec': effective_setpoint_ec,
            'effective_hysteresis_ec': effective_hysteresis_ec,
            'range_ec_low': range_ec_low,
            'range_ec_high': range_ec_high,
            'ec_high_threshold': effective_ec_high_threshold,
            'max_ec_before_dose': effective_max_ec_before_dose,
            'grow_start_date': grow_start,
            'grow_week': grow_week,
            'ec_age_coupling_enabled': ec_age_coupling_enabled,
            'ec_age_pct': ec_age_pct,
        }
    except Exception as e:
        log.warning("Regulator config read error: %s", e)
        return None


# ── Trend Data ────────────────────────────────────────────────────────────────


def read_trends(hours: int = 6) -> dict:
    """Read trend data (min/max/samples) for pH and EC over past hours."""
    trends = {}
    secs = hours * 3600

    # pH trend
    try:
        result = query_flux('pH', '97f9e370-d63b-43c5-82fd-fb0c407b687e',
                            past_sec=secs, group_sec=1800)
        if result:
            vals = [r.get_value() for t in result for r in t.records
                    if r.get_value() is not None]
            if vals:
                trends['pH'] = vals
    except Exception as e:
        log.debug("pH trend error: %s", e)

    # EC trend
    try:
        result = query_flux('uS_cm', '97f9e370-d63b-43c5-82fd-fb0c407b687e',
                            channel=1, past_sec=secs, group_sec=1800)
        if result:
            vals = [r.get_value() for t in result for r in t.records
                    if r.get_value() is not None]
            if vals:
                trends['EC'] = vals
    except Exception as e:
        log.debug("EC trend error: %s", e)

    return trends


# ── Camera & Vision ───────────────────────────────────────────────────────────


def capture_snapshot() -> bytes | None:
    """Grab a JPEG snapshot from the grow camera."""
    try:
        resp = requests.get(
            CAMERA_SNAPSHOT_URL,
            auth=CAMERA_AUTH,
            timeout=10)
        if resp.ok and len(resp.content) > 1000:
            return resp.content
        log.warning("Camera snapshot failed: %s (%d bytes)",
                     resp.status_code, len(resp.content))
        return None
    except Exception as e:
        log.warning("Camera error: %s", e)
        return None


def tg_send_photo(photo_bytes: bytes, caption: str = "") -> bool:
    """Send a photo to Telegram."""
    try:
        resp = requests.post(
            f"{TG_BASE}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"photo": ("snapshot.jpg", photo_bytes, "image/jpeg")},
            timeout=30,
        )
        return resp.ok
    except Exception as e:
        log.warning("Telegram photo error: %s", e)
        return False


def vision_analyze(photo_bytes: bytes, question: str = "") -> str | None:
    """Send photo to vision model for analysis."""
    return vision_analyze_multi([photo_bytes], question)


def vision_analyze_multi(photos: list[bytes], question: str = "") -> str | None:
    """Send one or more photos to vision model for analysis."""
    global LAST_VISION_ERROR
    LAST_VISION_ERROR = None

    prompt = (
        "Analyseer deze foto van een cannabis zaailing in een NFT hydroponics systeem. "
        "Beschrijf kort: plantgezondheid, bladkleur, grootte, en eventuele problemen. "
        "Antwoord in het Nederlands, max 3-4 zinnen."
    )
    if question:
        prompt = question

    # Build content: text prompt + all images
    content: list[dict] = [{"type": "text", "text": prompt}]
    for photo in photos:
        b64 = base64.b64encode(photo).decode('ascii')
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    total_kb = sum(len(p) for p in photos) // 1024
    log.info("[VISION:req] model=%s photos=%d total=%dKB prompt=%s",
             VISION_MODEL, len(photos), total_kb, prompt[:100])

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        resp = requests.post(
            LLM_API_URL,
            headers=headers,
            json={
                "model": VISION_MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 1024,
                "temperature": 0.4,
                "stream": False,
            },
            timeout=300,
        )
        if resp.ok:
            data = resp.json()
            usage = data.get("usage", {})
            choices = data.get("choices", [])
            if choices:
                result = choices[0].get("message", {}).get("content", "").strip()
                log.info("[VISION:resp] tokens=%s len=%d: %s",
                         usage.get("total_tokens", "?"), len(result), result[:200])
                return result
            log.warning("[VISION:err] No choices in response")
            LAST_VISION_ERROR = "⚠️ Vision backend gaf geen bruikbare output terug."
        else:
            log.warning("[VISION:err] HTTP %s: %s", resp.status_code, resp.text[:200])
            if (resp.status_code == 500 and
                    VISION_UNSUPPORTED_ERROR_FRAGMENT in resp.text):
                LAST_VISION_ERROR = VISION_UNSUPPORTED_USER_MESSAGE
            else:
                LAST_VISION_ERROR = "⚠️ Vision analyse mislukt."
        return None
    except Exception as e:
        log.error("[VISION:err] %s", e)
        LAST_VISION_ERROR = "⚠️ Vision analyse mislukt."
        return None


# ── Telegram API ──────────────────────────────────────────────────────────────

TG_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def tg_send(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to Telegram."""
    try:
        resp = requests.post(
            f"{TG_BASE}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        if not resp.ok:
            # Retry without parse_mode if Markdown fails
            if parse_mode:
                return tg_send(text, parse_mode="")
            log.warning("Telegram send failed: %s", resp.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("Telegram error: %s", e)
        return False


def tg_download_photo(file_id: str) -> bytes | None:
    """Download a photo from Telegram by file_id."""
    try:
        resp = requests.get(f"{TG_BASE}/getFile", params={"file_id": file_id}, timeout=10)
        if not resp.ok:
            log.warning("getFile failed: %s", resp.text[:200])
            return None
        file_path = resp.json().get("result", {}).get("file_path")
        if not file_path:
            return None
        dl_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        dl = requests.get(dl_url, timeout=30)
        return dl.content if dl.ok else None
    except Exception as e:
        log.error("Photo download error: %s", e)
        return None


def tg_send_typing():
    """Send 'typing' action to show bot is working."""
    try:
        requests.post(
            f"{TG_BASE}/sendChatAction",
            json={"chat_id": TELEGRAM_CHAT_ID, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


def tg_get_updates(offset: int | None = None, timeout: int = 30) -> list:
    """Long-poll for new Telegram messages."""
    params = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(
            f"{TG_BASE}/getUpdates",
            params=params,
            timeout=timeout + 10,
        )
        if resp.ok:
            return resp.json().get("result", [])
    except Exception as e:
        log.warning("Telegram poll error: %s", e)
    return []


# ── LLM Chat ─────────────────────────────────────────────────────────────────



def _guardian_headers() -> dict:
    """Build Guardian request headers with Bearer auth."""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers

def _guardian_log_queue_headers(resp: requests.Response, tag: str):
    """Log queue metadata headers exposed by Guardian."""
    req_id = resp.headers.get("X-Request-Id", "")
    wait_ms = resp.headers.get("X-Queue-Wait-Ms", "")
    if req_id or wait_ms:
        log.info("[%s] queue request_id=%s wait_ms=%s", tag, req_id or "-", wait_ms or "-")

def _guardian_queue_status_snapshot(timeout_s: int = 5) -> dict | None:
    """Get current queue status for diagnostics."""
    try:
        resp = requests.get(GUARDIAN_QUEUE_STATUS_URL, headers=_guardian_headers(), timeout=timeout_s)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None

def _guardian_force_load_model(model: str) -> bool:
    """Attempt to jump-start a stuck model via /admin/load."""
    if not model or not GUARDIAN_ADMIN_LOAD_URL:
        return False
    try:
        resp = requests.post(GUARDIAN_ADMIN_LOAD_URL, headers=_guardian_headers(), json={"model": model}, timeout=10)
        if resp.ok:
            log.warning("[GUARDIAN] Forced model load OK: %s", model)
            return True
        log.warning("[GUARDIAN] Force-load failed HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.warning("[GUARDIAN] Force-load error: %s", e)
        return False

def _guardian_post_chat(payload: dict, timeout_s: int, tag: str) -> requests.Response | None:
    """POST to Guardian chat endpoint with queue resilience.
    
    If Guardian is serving other clients (e.g. 429 queue full, or requests.Timeout),
    we patiently wait our turn instead of dropping the Telegram message.
    """
    t0_global = time.monotonic()
    max_wait_total = 1800  # Give up after 30 minutes total queue wait

    while (time.monotonic() - t0_global) < max_wait_total:
        try:
            resp = requests.post(
                LLM_API_URL,
                headers=_guardian_headers(),
                json=payload,
                timeout=timeout_s,
            )
            _guardian_log_queue_headers(resp, tag)

            if resp.status_code == 503:
                model = payload.get("model", "")
                log.warning("[%s] HTTP 503, trying Guardian recovery for model=%s", tag, model)
                _guardian_force_load_model(model)
                time.sleep(GUARDIAN_RECOVER_RETRY_DELAY_S)
                continue
                
            if resp.status_code == 429:
                wait_s = 30
                q = _guardian_queue_status_snapshot()
                if q:
                    wait_s = max(10, float(q.get("your_wait_s", 30) or 30))
                    log.warning("[%s] Guardian busy (429). Pos=%s, Active=%s, Len=%s. Retrying in %.1fs...",
                                tag, q.get("your_position", "?"),
                                q.get("active_count", "?"), q.get("queue_length", "?"), wait_s)
                else:
                    log.warning("[%s] Guardian busy (429). Retrying in 30s...", tag)
                
                time.sleep(min(wait_s, 60))
                continue

            return resp

        except requests.exceptions.Timeout:
            log.warning("[%s] Local timeout after %ss, Guardian might be very busy. Retrying...", tag, timeout_s)
            time.sleep(5)
            continue
            
        except Exception as e:
            log.error("[%s] Unexpected request error: %s", tag, e)
            time.sleep(5)
            continue

    log.error("[%s] Gave up after waiting >30m for Guardian.", tag)
    return None


def _guardian_headers() -> dict:
    """Build Guardian request headers with Bearer auth."""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers

def _guardian_log_queue_headers(resp: requests.Response, tag: str):
    """Log queue metadata headers exposed by Guardian."""
    req_id = resp.headers.get("X-Request-Id", "")
    wait_ms = resp.headers.get("X-Queue-Wait-Ms", "")
    if req_id or wait_ms:
        log.info("[%s] queue request_id=%s wait_ms=%s", tag, req_id or "-", wait_ms or "-")

def _guardian_queue_status_snapshot(timeout_s: int = 5) -> dict | None:
    """Get current queue status for diagnostics."""
    try:
        resp = requests.get(GUARDIAN_QUEUE_STATUS_URL, headers=_guardian_headers(), timeout=timeout_s)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None

def _guardian_force_load_model(model: str) -> bool:
    """Attempt to jump-start a stuck model via /admin/load."""
    if not model or not GUARDIAN_ADMIN_LOAD_URL:
        return False
    try:
        resp = requests.post(GUARDIAN_ADMIN_LOAD_URL, headers=_guardian_headers(), json={"model": model}, timeout=10)
        if resp.ok:
            log.warning("[GUARDIAN] Forced model load OK: %s", model)
            return True
        log.warning("[GUARDIAN] Force-load failed HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.warning("[GUARDIAN] Force-load error: %s", e)
        return False

def _guardian_post_chat(payload: dict, timeout_s: int, tag: str) -> requests.Response | None:
    """POST to Guardian chat endpoint with queue resilience.
    
    If Guardian is serving other clients (e.g. 429 queue full, or requests.Timeout),
    we patiently wait our turn instead of dropping the Telegram message.
    """
    t0_global = time.monotonic()
    max_wait_total = 1800  # Give up after 30 minutes total queue wait

    while (time.monotonic() - t0_global) < max_wait_total:
        try:
            resp = requests.post(
                LLM_API_URL,
                headers=_guardian_headers(),
                json=payload,
                timeout=timeout_s,
            )
            _guardian_log_queue_headers(resp, tag)

            if resp.status_code == 503:
                model = payload.get("model", "")
                log.warning("[%s] HTTP 503, trying Guardian recovery for model=%s", tag, model)
                _guardian_force_load_model(model)
                time.sleep(GUARDIAN_RECOVER_RETRY_DELAY_S)
                continue
                
            if resp.status_code == 429:
                wait_s = 30
                q = _guardian_queue_status_snapshot()
                if q:
                    wait_s = max(10, float(q.get("your_wait_s", 30) or 30))
                    log.warning("[%s] Guardian busy (429). Pos=%s, Active=%s, Len=%s. Retrying in %.1fs...",
                                tag, q.get("your_position", "?"),
                                q.get("active_count", "?"), q.get("queue_length", "?"), wait_s)
                else:
                    log.warning("[%s] Guardian busy (429). Retrying in 30s...", tag)
                
                time.sleep(min(wait_s, 60))
                continue

            return resp

        except requests.exceptions.Timeout:
            log.warning("[%s] Local timeout after %ss, Guardian might be very busy. Retrying...", tag, timeout_s)
            time.sleep(5)
            continue
            
        except Exception as e:
            log.error("[%s] Unexpected request error: %s", tag, e)
            time.sleep(5)
            continue

    log.error("[%s] Gave up after waiting >30m for Guardian.", tag)
    return None

def llm_chat(messages: list[dict]) -> str | None:


    """Send messages to Guardian LLM and return assistant response."""
    log.info("[LLM:req] model=%s msgs=%d", LLM_MODEL, len(messages))
    t0 = time.monotonic()
    try:
        resp = _guardian_post_chat(
            payload={
                "model": LLM_MODEL,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.5,
                "stream": False,
            },
            timeout_s=GUARDIAN_DEFAULT_TIMEOUT,
            tag="LLM"
        )
        if not resp or not resp.ok:
            if resp: log.warning("[LLM:err] HTTP %s: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()
        usage = data.get("usage", {})
        choices = data.get("choices", [])
        if choices:
            result = choices[0].get("message", {}).get("content", "").strip()
            log.info("[LLM:resp] tokens=%s len=%d: %s",
                     usage.get("total_tokens", "?"), len(result), result[:200])
            return result
        log.warning("[LLM:err] No choices in response")
        return None
    except Exception as e:
        log.error("[LLM:err] %s", e)
        return None


# ── Persistent Memory ─────────────────────────────────────────────────────────


class MemoryStore:
    """SQLite-backed persistent memory: conversations + extracted observations."""

    def __init__(self, db_path: str = BOT_MEMORY_DB):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
                role        TEXT NOT NULL,     -- user / assistant / system
                content     TEXT NOT NULL,
                command     TEXT,              -- /status, /wortel, free-form, etc.
                tokens_used INTEGER
            );
            CREATE TABLE IF NOT EXISTS observations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
                category    TEXT NOT NULL,     -- roots, ph, ec, dosing, plant, general
                summary     TEXT NOT NULL,     -- short fact
                score       REAL,             -- optional numeric score (e.g. root health 1-10)
                source      TEXT              -- which command produced this
            );
            CREATE INDEX IF NOT EXISTS idx_obs_cat ON observations(category);
            CREATE INDEX IF NOT EXISTS idx_obs_ts  ON observations(ts);
            CREATE INDEX IF NOT EXISTS idx_msg_ts  ON messages(ts);
        """)
        self.db.commit()

    def save_message(self, role: str, content: str, command: str = None,
                     tokens: int = None):
        """Persist a single message."""
        self.db.execute(
            "INSERT INTO messages(role, content, command, tokens_used) VALUES(?,?,?,?)",
            (role, content, command, tokens)
        )
        self.db.commit()

    def save_observation(self, category: str, summary: str, score: float = None,
                         source: str = None):
        """Store an extracted fact/observation."""
        self.db.execute(
            "INSERT INTO observations(category, summary, score, source) VALUES(?,?,?,?)",
            (category, summary, score, source)
        )
        self.db.commit()
        log.info("[MEM:obs] %s: %s (score=%s)", category, summary[:100], score)

    def get_recent_messages(self, limit: int = MAX_HISTORY,
                            since_ts: str | None = None,
                            include_assistant: bool = True) -> list[dict]:
        """Load last N user/assistant messages for conversation continuity."""
        roles = ['user', 'assistant'] if include_assistant else ['user']
        placeholders = ','.join('?' for _ in roles)
        query = (
            "SELECT role, content FROM messages "
            f"WHERE role IN ({placeholders})"
        )
        params: list[str | int] = list(roles)
        if since_ts:
            query += " AND ts >= ?"
            params.append(since_ts)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.db.execute(query, tuple(params)).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def get_recent_observations(self, limit: int = 10,
                                since_ts: str | None = None) -> list[dict]:
        """Get most recent observations across all categories."""
        query = "SELECT ts, category, summary, score FROM observations"
        params: list[str | int] = []
        if since_ts:
            query += " WHERE ts >= ?"
            params.append(since_ts)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.db.execute(query, tuple(params)).fetchall()
        return [{"ts": r[0], "category": r[1], "summary": r[2], "score": r[3]}
                for r in reversed(rows)]

    def get_observations_by_category(self, category: str, limit: int = 5,
                                     since_ts: str | None = None) -> list[dict]:
        """Get recent observations for a specific category."""
        query = (
            "SELECT ts, summary, score FROM observations "
            "WHERE category = ?"
        )
        params: list[str | int] = [category]
        if since_ts:
            query += " AND ts >= ?"
            params.append(since_ts)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.db.execute(query, tuple(params)).fetchall()
        return [{"ts": r[0], "summary": r[1], "score": r[2]} for r in reversed(rows)]

    def get_message_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def get_observation_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


# ── Conversation Manager ──────────────────────────────────────────────────────


class ConversationManager:
    """Manages conversation history with persistent SQLite memory."""

    EXTRACT_PROMPT = (
        "Extraheer 0-3 korte feiten uit dit gesprek die later nuttig zijn. "
        "Focus op: wortelgezondheid, pH/EC observaties, doseeradviezen, "
        "plantgroei, problemen, of acties.\n"
        "Formaat: één feit per regel, prefix met categorie:\n"
        "roots: ...\nph: ...\nec: ...\ndosing: ...\nplant: ...\ngeneral: ...\n"
        "Als er een score is (bijv wortelgezondheid), voeg toe als score=N\n"
        "Als er niets belangrijks is, antwoord: GEEN\n\n"
        "Gesprek:\nUser: {user}\nAssistant: {assistant}"
    )

    def __init__(self):
        self.mem = MemoryStore()
        self.current_run_since = CURRENT_RUN_CONTEXT_TS
        # Load persisted history
        self.history = self.mem.get_recent_messages(
            MAX_HISTORY,
            since_ts=self.current_run_since,
            include_assistant=False)
        n_msgs = self.mem.get_message_count()
        n_obs = self.mem.get_observation_count()
        log.info("[MEM] Loaded: %d messages, %d observations, history=%d",
                 n_msgs, n_obs, len(self.history))

    def _build_system_prompt(self, sensor_data: dict) -> str:
        """Build system prompt with lore + sensors + dosing + trends + memory."""
        # Current readings
        parts = [
            f"\n\n### Huidige Sensordata ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            f"Grow dag: {sensor_data.get('grow_day', '?')} (week {sensor_data.get('grow_week', '?')})",
            f"Fase: {sensor_data.get('phase', '?')}",
            (
                f"Actieve run-startdatum: {GROW_START_DATE}. Gebruik deze datum als "
                f"enige bron voor de leeftijd van de huidige plant; oudere runs en "
                f"oude chatgesprekken zijn alleen historische context."
            ),
        ]
        ph = sensor_data.get('ph')
        ec = sensor_data.get('ec')
        vol = sensor_data.get('volume')
        flow = sensor_data.get('flow')
        parts.append(f"pH: {ph:.2f}" if ph is not None else "pH: geen data")
        parts.append(f"EC: {ec:.0f} µS/cm" if ec is not None else "EC: geen data")
        parts.append(f"Waterpeil: {vol:.1f} L" if vol is not None else "Waterpeil: geen data")
        parts.append(f"Flow: {flow:.3f} L/min" if flow is not None else "Flow: geen data")

        # Dosing today
        dosed = read_dosing_today()
        if dosed:
            parts.append("")
            parts.append("### Vandaag Gedoseerd")
            parts.append(f"pH Down: {dosed.get('ph_ml', 0):.1f} ml")
            parts.append(f"EC A (Sensi A): {dosed.get('ec_a_ml', 0):.1f} ml")
            parts.append(f"EC B (Sensi B): {dosed.get('ec_b_ml', 0):.1f} ml")

        regulator = read_regulator_config()
        if regulator:
            parts.append("")
            parts.append("### Actieve Regulatorconfig (live uit Mycodo DB)")
            if regulator.get('range_ec_low') is not None and regulator.get('range_ec_high') is not None:
                parts.append(
                    "EC band: "
                    f"{regulator['range_ec_low']:.0f}–{regulator['range_ec_high']:.0f} µS/cm "
                    f"(week {regulator['grow_week']}, {regulator['ec_age_pct']:.0f}% van volwassen target)"
                )
            if regulator.get('max_ec_before_dose') is not None:
                parts.append(
                    "Nutriëntenschema blokkeert extra dosering boven: "
                    f"{regulator['max_ec_before_dose']:.0f} µS/cm"
                )
            if regulator.get('ec_high_threshold') is not None:
                parts.append(
                    "High-EC waarschuwing vanaf: "
                    f"{regulator['ec_high_threshold']:.0f} µS/cm"
                )
            if sensor_data.get('phase') == 'zaailing':
                parts.append(
                    "Omdat dit een zaailing is, moet je expliciet benoemen als de live "
                    "EC-band hoog oogt voor week 1. Beschrijf dat dan als een "
                    "configuratiekeuze van de regulator, niet als een meetfout."
                )

        # Trends
        trends = read_trends()
        if trends:
            parts.append("")
            parts.append("### Trends (laatste 6 uur)")
            for name, vals in trends.items():
                if vals and len(vals) >= 2:
                    parts.append(f"{name}: {vals[0]:.1f} → {vals[-1]:.1f} (delta: {vals[-1]-vals[0]:+.1f})")

        # Disabled sensors
        parts.append("")
        parts.append("### Niet-actieve sensoren")
        parts.append("- DS18B20 watertemperatuur: UITGESCHAKELD (geen data)")
        parts.append("- DHT22 ambient temp/RV: UITGESCHAKELD (geen data)")

        # ── MEMORY: inject recent observations ──
        obs = self.mem.get_recent_observations(
            limit=15, since_ts=self.current_run_since)
        if obs:
            parts.append("")
            parts.append("### Geheugen — Recente Observaties")
            parts.append("(Dit zijn feiten uit eerdere gesprekken die je onthoudt)")
            for o in obs:
                score_str = f" [score: {o['score']:.0f}/10]" if o['score'] is not None else ""
                parts.append(f"- [{o['ts'][:10]}] ({o['category']}) {o['summary']}{score_str}")

        # Root scan history
        root_obs = self.mem.get_observations_by_category(
            "roots", limit=5, since_ts=self.current_run_since)
        if root_obs and not any(o['category'] == 'roots' for o in obs[:5]):
            parts.append("")
            parts.append("### Wortelgeschiedenis")
            for r in root_obs:
                score_str = f" [{r['score']:.0f}/10]" if r['score'] is not None else ""
                parts.append(f"- [{r['ts'][:10]}] {r['summary']}{score_str}")

        return SYSTEM_LORE + "\n".join(parts)

    def _extract_observations(self, user_msg: str, assistant_msg: str, source: str = "chat"):
        """Ask LLM to extract key facts from the exchange, store in memory."""
        prompt = self.EXTRACT_PROMPT.format(user=user_msg[:500], assistant=assistant_msg[:1000])
        try:
            result = llm_chat([
                {"role": "system", "content": "Je bent een data-extractie tool. Antwoord ALLEEN in het gevraagde formaat."},
                {"role": "user", "content": prompt}
            ])
            if not result or "GEEN" in result.upper():
                return

            for line in result.strip().split("\n"):
                line = line.strip()
                if not line or ":" not in line:
                    continue
                # Parse "category: summary text score=N"
                cat, _, text = line.partition(":")
                cat = cat.strip().lower()
                text = text.strip()
                if cat not in ("roots", "ph", "ec", "dosing", "plant", "general"):
                    continue

                # Extract optional score
                score = None
                if "score=" in text.lower():
                    m = re.search(r'score\s*=\s*([\d.]+)', text, re.IGNORECASE)
                    if m:
                        score = float(m.group(1))
                        text = re.sub(r'\s*score\s*=\s*[\d.]+', '', text, flags=re.IGNORECASE).strip()

                if text:
                    # If LLM indicates a reminder was processed/deleted
                    if '[REMINDER_DELETE]' in text or '[REMINDER_UPDATE]' in text:
                        self.mem.save_message('system', f'Updated reminder: {text}', command='/reminder')
                    else:
                        self.mem.save_observation(cat, text, score=score, source=source)
                    self.mem.save_observation(cat, text, score=score, source=source)

        except Exception as e:
            log.warning("[MEM:extract] Failed: %s", e)

    def handle_message(self, text: str, command: str = "chat") -> str:
        """Process a user message and return a response."""
        # Read fresh sensor data
        sensor_data = read_sensors()
        system_prompt = self._build_system_prompt(sensor_data)

        # Add user message to history + persist
        self.history.append({"role": "user", "content": text})
        self.mem.save_message("user", text, command=command)

        # Trim history
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

        # Build full message list
        messages = [{"role": "system", "content": system_prompt}] + self.history

        # Call LLM
        response = llm_chat(messages)
        if not response:
            return "⚠️ Kon geen antwoord krijgen van de LLM. Probeer het later nog eens."

        # Persist assistant response
        self.history.append({"role": "assistant", "content": response})
        self.mem.save_message("assistant", response, command=command)

        # Background fact extraction (non-blocking for user, but we do it inline
        # since we're already in a polling loop)
        self._extract_observations(text, response, source=command)

        return response

    def save_vision_observation(self, analysis: str, source: str = "vision"):
        """Store a vision analysis result as observation."""
        # Try to extract a score from the analysis
        score = None
        m = re.search(r'(?:score|gezondheid)[:\s]*(\d+)\s*/\s*10', analysis, re.IGNORECASE)
        if m:
            score = float(m.group(1))

        category = "roots" if source in ("wortel", "/wortel") else "plant"
        summary = analysis[:300]
        self.mem.save_observation(category, summary, score=score, source=source)

    def get_status(self) -> str:
        """Return formatted sensor status (no LLM)."""
        return format_status(read_sensors())

    def get_advice(self) -> str:
        """Ask LLM specifically for dosing advice."""
        return self.handle_message(
            "Geef me een doseeradvies op basis van de huidige sensordata. "
            "Wat zou je aanraden voor vandaag? Wees specifiek.",
            command="/advies"
        )

    def reset(self):
        """Clear in-memory history (DB log preserved)."""
        self.history.clear()
        self.mem.save_message("system", "Conversation reset by user", command="/reset")


# ── Main Bot Loop ─────────────────────────────────────────────────────────────

_running = True


def _signal_handler(sig, frame):
    global _running
    log.info("Shutdown signal received")
    _running = False


def main():
    global _running
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _validate_runtime_config()
    log.info("🤖 Telegram Grow Bot starting...")
    conv = ConversationManager()
    offset = None

    # Startup message
    tg_send(
        "🤖 *Grow Bot online!*\n\n"
        "Commands:\n"
        "/status — Sensor snapshot + dosering + trends\n"
        "/advies — Doseeradvies van de LLM\n"
        "/foto — Camera snapshot + visuele analyse\n"
        "/wortel — Wortelcheck via camera\n"
        "/trend — pH/EC trend afgelopen 6 uur\n"
        "/geheugen — Wat de bot onthoud\n"
        "/reset — Gesprek resetten\n"
        "📷 Je kunt ook gewoon een foto sturen!\n"
        "Of gewoon een vraag stellen!"
    )

    log.info("Bot running, polling for messages...")

    while _running:
        updates = tg_get_updates(offset=offset, timeout=30)

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})

            # Only respond to our chat
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != TELEGRAM_CHAT_ID:
                log.warning("Ignoring message from chat_id=%s", chat_id)
                continue

            text = (msg.get("text") or "").strip()
            photo_list = msg.get("photo")
            user_name = msg.get("from", {}).get("first_name", "User")

            # ── Handle incoming photo ──
            if photo_list:
                caption = (msg.get("caption") or "").strip()
                log.info("[IN:photo] %s: caption=%s", user_name, caption[:100] if caption else "none")
                file_id = photo_list[-1]["file_id"]  # largest resolution
                tg_send_typing()
                photo_bytes = tg_download_photo(file_id)
                if not photo_bytes:
                    err = "❌ Kon de foto niet downloaden."
                    tg_send(err)
                    append_grow_log_check("photo-upload", err)
                    continue

                prompt = caption if caption else (
                    "Analyseer deze foto van een cannabis zaailing in een NFT "
                    "hydroponics systeem. Beschrijf kort: plantgezondheid, bladkleur, "
                    "grootte, en eventuele problemen. Antwoord in het Nederlands, max 3-4 zinnen."
                )
                analysis = vision_analyze(photo_bytes, prompt)
                if analysis:
                    log.info("[OUT:vision] %s", analysis[:200])
                    conv.save_vision_observation(analysis, source="photo")
                    tg_send(f"👁️ Visuele analyse:\n\n{analysis}", parse_mode="")
                    append_grow_log_check("photo-upload", analysis)
                else:
                    err = LAST_VISION_ERROR or "⚠️ Vision analyse mislukt."
                    tg_send(err)
                    append_grow_log_check("photo-upload", err)
                continue

            if not text:
                continue

            log.info("[IN] %s: %s", user_name, text[:200])

            # Handle commands
            cmd = text.lower().split()[0] if text else ""

            if cmd == "/status":
                tg_send_typing()
                status_data = read_sensors()
                reply = format_status(status_data)
                log.info("[OUT] %s", reply[:200])
                tg_send(reply)
                append_grow_log_check("/status", _status_summary(status_data))

            elif cmd == "/advies":
                tg_send_typing()
                reply = conv.get_advice()
                log.info("[OUT] %s", reply[:200])
                tg_send(reply, parse_mode="")
                append_grow_log_check("/advies", reply)

            elif cmd == "/reset":
                conv.reset()
                log.info("[OUT:reset] Conversation cleared")
                tg_send("🔄 Gesprek gereset. Stel gerust een nieuwe vraag!")

            elif cmd == "/foto":
                tg_send_typing()
                photo = capture_snapshot()
                if photo:
                    tg_send_photo(photo, "📸 Live snapshot")
                    tg_send_typing()
                    extra_q = text[5:].strip() if len(text) > 5 else ""
                    analysis = vision_analyze(photo, extra_q if extra_q else "")
                    if analysis:
                        log.info("[OUT:vision] %s", analysis[:200])
                        conv.save_vision_observation(analysis, source="/foto")
                        tg_send(f"👁️ Visuele analyse:\n\n{analysis}", parse_mode="")
                        append_grow_log_check("/foto", analysis)
                    else:
                        log.warning("[OUT:foto] Vision analyse mislukt")
                        err = LAST_VISION_ERROR or "⚠️ Vision analyse mislukt."
                        tg_send(err)
                        append_grow_log_check("/foto", err)
                else:
                    err = "❌ Kon geen foto maken van de camera."
                    log.warning("[OUT:foto] Camera snapshot failed")
                    tg_send(err)
                    append_grow_log_check("/foto", err)

            elif cmd == "/wortel":
                SCAN_DURATION = 120   # 2 minutes
                SCAN_INTERVAL = 10    # every 10 sec
                total_shots = SCAN_DURATION // SCAN_INTERVAL  # 12

                log.info("[wortel] Scan started: %d shots, %ds interval", total_shots, SCAN_INTERVAL)
                tg_send(
                    f"🌱 *Wortel Scan gestart!*\n\n"
                    f"📸 {total_shots} foto's in {SCAN_DURATION // 60} minuten "
                    f"(elke {SCAN_INTERVAL}s)\n"
                    f"Houd de wortels voor de camera — draai ze langzaam rond."
                )

                photos: list[bytes] = []
                for i in range(total_shots):
                    if i > 0:
                        time.sleep(SCAN_INTERVAL)
                    snap = capture_snapshot()
                    if snap:
                        photos.append(snap)
                        log.info("[wortel] Snapshot %d/%d (%d KB)",
                                 i + 1, total_shots, len(snap) // 1024)
                    else:
                        log.warning("[wortel] Snapshot %d/%d FAILED", i + 1, total_shots)

                log.info("[wortel] Capture done: %d/%d successful", len(photos), total_shots)
                if not photos:
                    log.warning("[wortel] All snapshots failed")
                    err = "❌ Geen enkele snapshot gelukt."
                    tg_send(err)
                    append_grow_log_check("/wortel", err)
                    continue

                # Send best photos as album (Telegram max 10 per group)
                album_batch = photos[:10]
                try:
                    media = []
                    files = {}
                    for idx, p in enumerate(album_batch):
                        fname = f"photo{idx}"
                        media.append({
                            "type": "photo",
                            "media": f"attach://{fname}",
                            **({"caption": f"🌱 Wortel scan ({len(photos)} foto's)"} if idx == 0 else {}),
                        })
                        files[fname] = (f"{fname}.jpg", p, "image/jpeg")
                    resp = requests.post(
                        f"{TG_BASE}/sendMediaGroup",
                        data={"chat_id": TELEGRAM_CHAT_ID, "media": json.dumps(media)},
                        files=files,
                        timeout=60,
                    )
                    if not resp.ok:
                        log.warning("sendMediaGroup failed: %s", resp.text[:200])
                        # Fallback: send first and last
                        tg_send_photo(photos[0], f"🌱 Foto 1/{len(photos)}")
                        if len(photos) > 1:
                            tg_send_photo(photos[-1], f"🌱 Foto {len(photos)}/{len(photos)}")
                except Exception as e:
                    log.warning("Album send error: %s", e)
                    tg_send_photo(photos[0], f"🌱 Foto 1/{len(photos)}")

                # Vision analysis with all photos
                tg_send(f"🧠 Analyseer {len(photos)} foto's met Gemma4...")
                tg_send_typing()

                root_prompt = (
                    f"Je krijgt {len(photos)} foto's van de WORTELS van een cannabis plant "
                    f"in een NFT hydroponics systeem, genomen over {SCAN_DURATION // 60} minuten "
                    f"(elke {SCAN_INTERVAL} seconden). De plant groeit in een netpot met hydrokorrels.\n\n"
                    "Analyseer ALLE foto's samen en beoordeel:\n"
                    "1. Wortelkleur (wit=gezond, bruin=rot, slijmerig=problemen)\n"
                    "2. Wortelmassa en -dichtheid\n"
                    "3. Tekenen van wortelrot, algen, of pathogenen\n"
                    "4. Eventuele verschillen tussen de foto's (hoeken/zijden)\n"
                    "5. Algehele wortelgezondheid score (1-10)\n"
                    "6. Aanbevelingen als er problemen zijn\n\n"
                    "Antwoord in het Nederlands."
                )
                extra = text[7:].strip()
                if extra:
                    root_prompt += f"\n\nExtra context van de gebruiker: {extra}"

                analysis = vision_analyze_multi(photos, root_prompt)
                if analysis:
                    log.info("[OUT:wortel] %s", analysis[:300])
                    conv.save_vision_observation(analysis, source="/wortel")
                    tg_send(f"🌱 Wortelanalyse ({len(photos)} foto's):\n\n{analysis}", parse_mode="")
                    append_grow_log_check("/wortel", analysis)
                else:
                    err = LAST_VISION_ERROR or "⚠️ Vision analyse mislukt."
                    tg_send(err)
                    append_grow_log_check("/wortel", err)

            elif cmd == "/trend":
                tg_send_typing()
                trends = read_trends()
                if trends:
                    lines = ["📈 *Trends (6 uur)*", ""]
                    for name, vals in trends.items():
                        if vals and len(vals) >= 2:
                            mn, mx = min(vals), max(vals)
                            delta = vals[-1] - vals[0]
                            arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
                            lines.append(
                                f"{name}: {vals[0]:.1f} → {vals[-1]:.1f} "
                                f"({arrow}{abs(delta):.1f}) "
                                f"min={mn:.1f} max={mx:.1f}"
                            )
                    trend_msg = "\n".join(lines)
                    log.info("[OUT:trend] %s", trend_msg.replace("\n", " | ")[:200])
                    tg_send(trend_msg)
                    append_grow_log_check("/trend", _trend_summary(trends))
                else:
                    log.info("[OUT:trend] No trend data available")
                    err = "⚠️ Geen trend data beschikbaar."
                    tg_send(err)
                    append_grow_log_check("/trend", err)

            elif cmd == "/geheugen":
                obs = conv.mem.get_recent_observations(limit=15)
                n_msgs = conv.mem.get_message_count()
                n_obs = conv.mem.get_observation_count()
                lines = [
                    f"🧠 *Geheugen*",
                    f"💬 {n_msgs} berichten opgeslagen",
                    f"📝 {n_obs} observaties totaal",
                    "",
                ]
                if obs:
                    lines.append("*Recente observaties:*")
                    for o in obs:
                        score_str = f" [{o['score']:.0f}/10]" if o['score'] is not None else ""
                        lines.append(f"• `{o['ts'][:10]}` ({o['category']}) {o['summary'][:80]}{score_str}")
                else:
                    lines.append("_Nog geen observaties opgeslagen._")
                tg_send("\n".join(lines))

            elif cmd == "/help" or cmd == "/start":
                tg_send(
                    "🤖 *Grow Bot*\n\n"
                    "Commands:\n"
                    "/status — Sensor snapshot + dosering + trends\n"
                    "/advies — Doseeradvies van de LLM\n"
                    "/foto — Camera snapshot + visuele analyse\n"
                    "/wortel — Wortelcheck via camera\n"
                    "/trend — pH/EC trend afgelopen 6 uur\n"
                    "/geheugen — Wat de bot onthoud\n"
                    "/reset — Gesprek resetten\n"
                    "/help — Dit bericht\n\n"
                    "📷 Je kunt ook gewoon een foto sturen!\n"
                    "Of gewoon een vraag typen!"
                )

            else:
                # Free-form chat with LLM
                tg_send_typing()
                reply = conv.handle_message(text)
                log.info("[OUT] %s", reply[:300])
                tg_send(reply, parse_mode="")

    log.info("Bot stopped.")


if __name__ == "__main__":
    main()

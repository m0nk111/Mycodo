# coding=utf-8
"""
regulate_ph_ec_telegram.py — Custom Mycodo Function
Regulate pH and EC with Telegram alerts and XKC water level safety lock.

Features vs the built-in "Regulate pH and Electrical Conductivity":
  - Telegram notifications instead of email (bot_token + chat_id configurable)
  - Water level safety lock: reads XKC LOW sensor (GPIO22); blocks ALL dosing
    when reservoir is dry and sends Telegram alert
  - pH Down only (no pH Up output — we don't have pH Up)
  - EC nutrients A + B dosed simultaneously (equal duration/volume)
  - Danger range: when pH or EC is critically out of range, Telegram is sent
    immediately (not just on the next email timer)
  - Per-day dose limits: configurable max ml per day for pH Down and EC,
    prevents runaway dosing on faulty sensor readings
  - InfluxDB dose logging: writes dosed ml per event for dashboard graphs
  - Status panel shows last pH, EC, water level state, and dosing totals

Deploy:
  sudo cp regulate_ph_ec_telegram.py \
    /opt/Mycodo/mycodo/functions/custom_functions/regulate_ph_ec_telegram.py
  sudo chown mycodo:mycodo \
    /opt/Mycodo/mycodo/functions/custom_functions/regulate_ph_ec_telegram.py
  # Then restart Mycodo daemon
"""

import threading
import time
from datetime import date

import requests

from mycodo.databases.models import CustomController
from mycodo.functions.base_function import AbstractFunction
from mycodo.mycodo_client import DaemonControl
from mycodo.utils.constraints_pass import constraints_pass_positive_value
from mycodo.utils.database import db_retrieve_table_daemon
from mycodo.utils.influx import write_influxdb_value


def function_status_always(function_id):
    """Static status callable — required to prevent 'Could not get status' error.

    Returns empty string when the function is running (Activated route already
    shows everything). Only shows DB totals when the function is deactivated.
    """
    import json
    try:
        cc = db_retrieve_table_daemon(
            CustomController, unique_id=function_id)
        if not cc:
            return {'error': ['Function not found in database.']}

        # If function is activated, the instance method shows all data —
        # return empty to avoid duplication.
        if cc.is_activated:
            return {'string_status': '', 'error': []}

        # Deactivated: show DB totals so the widget isn't blank.
        opts = json.loads(cc.custom_options) if cc.custom_options else {}
        sec_ph = opts.get('sec_ph_lower', 0) or 0
        ml_ph = opts.get('ml_ph_lower', 0) or 0
        sec_a = opts.get('sec_ec_a', 0) or 0
        ml_a = opts.get('ml_ec_a', 0) or 0
        sec_b = opts.get('sec_ec_b', 0) or 0
        ml_b = opts.get('ml_ec_b', 0) or 0

        return {
            'string_status': (
                '<b>Functie is uitgeschakeld</b><br>&nbsp;'
                '<br><b>Totalen (all-time)</b>'
                f'<br>pH Down: {sec_ph:.1f} sec / {ml_ph:.1f} ml'
                f'<br>EC A: {sec_a:.1f} sec / {ml_a:.1f} ml'
                f'<br>EC B: {sec_b:.1f} sec / {ml_b:.1f} ml'
            ),
            'error': []
        }
    except Exception as e:
        return {'error': [str(e)]}


# ── Measurement channels (used by Mycodo to register InfluxDB series) ─────────
measurements_dict = {
    0: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'Dose pH Down'
    },
    1: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'Dose EC A'
    },
    2: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'Dose EC B'
    },
}

channels_dict = {
    0: {},
    1: {},
    2: {},
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'regulate_ph_ec_telegram',
    'function_name': 'Regulate pH and EC (Telegram Alerts)',
    'function_library': '',
    'manufacturer': 'Custom',
    'function_description': (
        'Regulate pH and Electrical Conductivity with Telegram notifications '
        'and XKC water level safety lock. pH Down only (no pH Up). '
        'EC nutrients A and B dosed equally.'
    ),
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'enable_channel_unit_select': False,
    'function_status': function_status_always,

    'options_enabled': [
        'custom_options',
        'function_status'
    ],

    'custom_commands_message': (
        'Reset dosing totals or alert timers. '
        'Telegram alert timers reset automatically after the configured interval.'
    ),

    'custom_commands': [
        {
            'id': 'reset_all_totals',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset All Dosing Totals'
        },
        {
            'id': 'reset_daily_dosed',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Daily Dose Counters (vandaag)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'reset_timer_all',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset All Telegram Alert Timers'
        },
        {
            'id': 'send_test_telegram',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Send Test Telegram Message'
        }
    ],

    'custom_options': [
        # ── Timing ────────────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Timing ──'
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Period (seconds)',
            'phrase': 'How often the regulation loop runs'
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': 'Start Offset (seconds)',
            'phrase': 'Wait this long after activation before first run'
        },

        # ── Measurements ──────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Measurements ──'
        },
        {
            'id': 'select_measurement_ph',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': 'pH Measurement',
            'phrase': 'Measurement from the pH input (ADS1115 A0)'
        },
        {
            'id': 'measurement_max_age_ph',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': 'pH Max Age (seconds)',
            'phrase': 'Reject pH readings older than this'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'select_measurement_ec',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': 'EC Measurement',
            'phrase': 'Measurement from the EC input (ADS1115 A1)'
        },
        {
            'id': 'measurement_max_age_ec',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': 'EC Max Age (seconds)',
            'phrase': 'Reject EC readings older than this'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'select_measurement_water_low',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': 'Water Level LOW Sensor (XKC GPIO22)',
            'phrase': 'GPIO_STATE input: 0=water present, 1=DRY → block dosing'
        },
        {
            'id': 'measurement_max_age_water',
            'type': 'integer',
            'default_value': 180,
            'required': True,
            'name': 'Water Level Max Age (seconds)',
            'phrase': 'Reject water level readings older than this'
        },
        {
            'id': 'select_measurement_water_high',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': 'Water Level HIGH Sensor (XKC GPIO27)',
            'phrase': 'GPIO_STATE input: 1=reservoir FULL (40L) → Telegram alert'
        },

        # ── Outputs ───────────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Outputs ──'
        },
        {
            'id': 'output_ph_lower',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': 'Output: pH Down (Pump 8)',
            'phrase': 'Pump to dose pH Down (acid) — lowers pH'
        },
        {
            'id': 'output_ph_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'pH Output Type',
            'phrase': 'Duration or volume per dose'
        },
        {
            'id': 'output_ph_amount',
            'type': 'float',
            'default_value': 3.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Output Amount',
            'phrase': 'Amount per dose (seconds or ml) — 3s = ~2.4 ml at 48 ml/min'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_a',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': 'Output: EC Nutrient A (Pump 1 — Sensi A)',
            'phrase': 'Pump for nutrient A — always dosed equally with B'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_b',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': 'Output: EC Nutrient B (Pump 2 — Sensi B)',
            'phrase': 'Pump for nutrient B — always dosed equally with A'
        },
        {
            'id': 'output_ec_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'EC Output Type',
            'phrase': 'Duration or volume per EC dose (applies to both A and B)'
        },
        {
            'id': 'output_ec_amount',
            'type': 'float',
            'default_value': 3.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Output Amount (A and B equal)',
            'phrase': 'Amount per dose for each of A and B (3s = ~2.4 ml each)'
        },

        # ── Setpoints ─────────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Setpoints ──'
        },
        {
            'id': 'setpoint_ph',
            'type': 'float',
            'default_value': 6.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Setpoint',
            'phrase': 'Target pH (center of band)'
        },
        {
            'id': 'hysteresis_ph',
            'type': 'float',
            'default_value': 0.2,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Hysteresis (± band)',
            'phrase': 'pH dose when outside setpoint ± hysteresis (default: 5.8–6.2)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'setpoint_ec',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Setpoint (mS/cm)',
            'phrase': 'Target EC in mS/cm'
        },
        {
            'id': 'hysteresis_ec',
            'type': 'float',
            'default_value': 0.2,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Hysteresis (± band)',
            'phrase': 'EC dose when < setpoint - hysteresis (default: dose when < 1.8)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'danger_ph_high',
            'type': 'float',
            'default_value': 7.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Danger High',
            'phrase': 'Immediately alert via Telegram if pH exceeds this (dosing still attempted)'
        },
        {
            'id': 'danger_ph_low',
            'type': 'float',
            'default_value': 5.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Danger Low',
            'phrase': 'Immediately alert via Telegram if pH drops below this (no pH Up available)'
        },
        {
            'id': 'ec_high_threshold',
            'type': 'float',
            'default_value': 2.6,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Too High Threshold (mS/cm)',
            'phrase': 'Alert via Telegram if EC exceeds this (dilute with RO water)'
        },

        # ── Dose Limits ────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Dose Limits (per dag) ──'
        },
        {
            'id': 'max_dose_ph_per_day_ml',
            'type': 'float',
            'default_value': 25.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Max pH Down per dag (ml)',
            'phrase': 'Maximale hoeveelheid pH Down per dag in ml (bijv. 25 = ~31s bij 48ml/min)'
        },
        {
            'id': 'max_dose_ec_per_day_ml',
            'type': 'float',
            'default_value': 100.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Max EC A+B per dag (ml elk)',
            'phrase': 'Maximale hoeveelheid per nutriënt A/B per dag in ml'
        },
        {
            'id': 'ml_per_min_ph',
            'type': 'float',
            'default_value': 48.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH pomp debiet (ml/min)',
            'phrase': 'Gecalibreerd debiet van de pH Down pomp (voor ml-berekening en logging)'
        },
        {
            'id': 'ml_per_min_ec',
            'type': 'float',
            'default_value': 48.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC pomp debiet (ml/min)',
            'phrase': 'Gecalibreerd debiet van de EC pompen A en B (voor ml-berekening en logging)'
        },

        # ── Telegram ──────────────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': '── Telegram Alerts ──'
        },
        {
            'id': 'telegram_bot_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Telegram Bot Token',
            'phrase': 'Token for @neut1bot (leave blank to disable Telegram)'
        },
        {
            'id': 'telegram_chat_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Telegram Chat ID',
            'phrase': 'Your personal Telegram chat ID'
        },
        {
            'id': 'telegram_alert_interval_hours',
            'type': 'float',
            'default_value': 4.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Telegram Alert Interval (hours)',
            'phrase': 'Minimum time between repeat alerts for the same condition'
        }
    ]
}


class CustomModule(AbstractFunction):
    """Regulate pH and EC with Telegram alerts and XKC water level safety."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()
        self.timer_loop = time.time()

        # ── options (populated by setup_custom_options) ──
        self.period = None
        self.start_offset = None

        self.select_measurement_ph_device_id = None
        self.select_measurement_ph_measurement_id = None
        self.measurement_max_age_ph = None

        self.select_measurement_ec_device_id = None
        self.select_measurement_ec_measurement_id = None
        self.measurement_max_age_ec = None

        self.select_measurement_water_low_device_id = None
        self.select_measurement_water_low_measurement_id = None
        self.measurement_max_age_water = None

        self.select_measurement_water_high_device_id = None
        self.select_measurement_water_high_measurement_id = None

        self.output_ph_lower_device_id = None
        self.output_ph_lower_channel_id = None
        self.output_ph_type = None
        self.output_ph_amount = None

        self.output_ec_a_device_id = None
        self.output_ec_a_channel_id = None
        self.output_ec_b_device_id = None
        self.output_ec_b_channel_id = None
        self.output_ec_type = None
        self.output_ec_amount = None

        self.setpoint_ph = None
        self.hysteresis_ph = None
        self.setpoint_ec = None
        self.hysteresis_ec = None
        self.danger_ph_high = None
        self.danger_ph_low = None
        self.ec_high_threshold = None

        self.telegram_bot_token = ''
        self.telegram_chat_id = ''
        self.telegram_alert_interval_hours = 4.0
        self.max_dose_ph_per_day_ml = 25.0
        self.max_dose_ec_per_day_ml = 100.0
        self.ml_per_min_ph = 48.0
        self.ml_per_min_ec = 48.0

        # ── internal state ──
        self.range_ph = (5.8, 6.2)
        self.range_ec = (1.8, 2.2)
        self._output_ph_lower_channel = None
        self._output_ec_a_channel = None
        self._output_ec_b_channel = None

        # Telegram alert timers — timestamp after which alert may fire again
        self._tg_timers = {
            'ph_low': 0, 'ph_high': 0, 'ph_danger_low': 0,
            'ec_low': 0, 'ec_high': 0,
            'water_dry': 0, 'water_full': 0, 'no_measurement': 0,
            'dose_limit': 0
        }

        # Per-day dose tracking (persistent in DB, resets at midnight)
        self._daily_dosed = self._load_daily_dosed()

        # Dosing totals (persistent via custom_option)
        self.total = {
            'sec_ph_lower': self._load('sec_ph_lower'),
            'ml_ph_lower':  self._load('ml_ph_lower'),
            'sec_ec_a':     self._load('sec_ec_a'),
            'ml_ec_a':      self._load('ml_ec_a'),
            'sec_ec_b':     self._load('sec_ec_b'),
            'ml_ec_b':      self._load('ml_ec_b'),
        }
        # Initialise missing totals to 0
        for k, v in self.total.items():
            if v is None:
                self.total[k] = self.set_custom_option(k, 0)

        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def initialize(self):
        self.timer_loop = time.time() + self.start_offset
        self.range_ph = (
            self.setpoint_ph - self.hysteresis_ph,
            self.setpoint_ph + self.hysteresis_ph
        )
        self.range_ec = (
            self.setpoint_ec - self.hysteresis_ec,
            self.setpoint_ec + self.hysteresis_ec
        )
        self._output_ph_lower_channel = self.get_output_channel_from_channel_id(
            self.output_ph_lower_channel_id)
        self._output_ec_a_channel = self.get_output_channel_from_channel_id(
            self.output_ec_a_channel_id)
        self._output_ec_b_channel = self.get_output_channel_from_channel_id(
            self.output_ec_b_channel_id)

        self.logger.info(
            f"pH/EC Telegram regulation active. "
            f"pH band: {self.range_ph[0]:.2f}–{self.range_ph[1]:.2f}, "
            f"EC band: {self.range_ec[0]:.2f}–{self.range_ec[1]:.2f} mS/cm"
        )

    def loop(self):
        if self.timer_loop > time.time():
            return
        while self.timer_loop < time.time():
            self.timer_loop += self.period

        # ── 1. Read measurements ──────────────────────────────────────────────
        val_ph = self._read('ph')
        val_ec = self._read('ec')
        val_water = self._read('water_low')   # None if sensor not configured
        val_water_high = self._read('water_high')  # None if sensor not configured

        missing = []
        if val_ph is None:
            missing.append('pH')
        if val_ec is None:
            missing.append('EC')
        if missing:
            msg = f"⚠️ [pH/EC Regulate] No measurement for: {', '.join(missing)}"
            self.logger.error(msg)
            self._tg_send_throttled('no_measurement', msg)
            return

        # Calibration extrapolation for ultra-pure / RO water yields slightly
        # negative EC due to the linear formula going below the lowest cal point.
        # Physically EC cannot be negative — clamp to 0.
        if val_ec < 0:
            self.logger.debug(
                f"EC={val_ec:.1f} µS/cm clamped to 0.0 "
                f"(calibration extrapolation below range — ultra-pure/RO water)"
            )
            val_ec = 0.0

        self.logger.debug(
            f"pH={val_ph:.3f}  EC={val_ec:.1f} µS/cm  "
            f"water_low={'DRY' if val_water == 1 else 'OK' if val_water == 0 else 'n/a'}  "
            f"water_high={'FULL' if val_water_high == 0 else 'OK' if val_water_high == 1 else 'n/a'}"
        )

        # ── 2. Sanity check — reject impossible sensor values ─────────────────
        errors = []
        if not (3.0 <= val_ph <= 10.0):
            errors.append(f"pH={val_ph:.2f} buiten bereik (3–10) — sensor niet in water?")
        if not (0.0 <= val_ec <= 10000.0):
            errors.append(f"EC={val_ec:.1f} µS/cm buiten bereik (0–10000) — sensor uitgevallen?")
        if errors:
            msg = "⚠️ [pH/EC] Ongeldige meting — dosing GEBLOKKEERD:\n" + "\n".join(errors)
            self.logger.error(msg)
            self._tg_send_throttled('no_measurement', msg)
            return

        # ── 3. Water level safety lock ────────────────────────────────────────
        if val_water == 1:
            # XKC GPIO22 HIGH = DRY at 15L mark — BLOCK ALL DOSING
            msg = (f"🚨 [pH/EC Regulate] WATER TOO LOW — dosing BLOCKED!\n"
                   f"XKC LOW sensor (GPIO22) = DRY.\n"
                   f"pH: {val_ph:.2f}  EC: {val_ec:.3f} mS/cm\n"
                   f"Refill reservoir before dosing resumes automatically.")
            self.logger.error(msg)
            self._tg_send_throttled('water_dry', msg)
            return

        # ── 3b. Water HIGH sensor — reservoir full alert ─────────────────────
        # pull_up: 0=water detected (FULL at 40L), 1=no water
        if val_water_high == 0:
            msg = (f"🪣 [pH/EC] RESERVOIR FULL (40L)\n"
                   f"XKC HIGH sensor (GPIO27) = WATER DETECTED.\n"
                   f"pH: {val_ph:.2f}  EC: {val_ec:.1f} µS/cm")
            self.logger.info(msg)
            self._tg_send_throttled('water_full', msg)

        # ── 3c. pH danger range (immediate Telegram, still dose if possible) ──
        if val_ph <= self.danger_ph_low:
            msg = (f"🚨 [pH/EC] pH CRITICALLY LOW: {val_ph:.2f}\n"
                   f"(danger threshold: {self.danger_ph_low:.2f})\n"
                   f"No pH Up available — manual intervention required!")
            self._tg_send_throttled('ph_danger_low', msg)
            self.logger.error(msg)
            # Can't dose pH up — just alert and stop pH regulation
        elif val_ph >= self.danger_ph_high:
            msg = (f"🚨 [pH/EC] pH CRITICALLY HIGH: {val_ph:.2f}\n"
                   f"(danger threshold: {self.danger_ph_high:.2f})\n"
                   f"Dosing pH Down now...")
            self._tg_send_throttled('ph_high', msg)
            self.logger.error(msg)
            self._dose_ph_lower(val_ph, val_ec)
            return

        # ── 4. EC too high — alert only, add RO water manually ───────────────
        if val_ec >= self.ec_high_threshold:
            msg = (f"⚠️ [pH/EC] EC TOO HIGH: {val_ec:.3f} mS/cm\n"
                   f"(threshold: {self.ec_high_threshold:.2f} mS/cm)\n"
                   f"Add RO water to dilute. No automatic action.")
            self._tg_send_throttled('ec_high', msg)
            self.logger.warning(msg)
            # Fall through — still regulate pH

        # ── 5. EC low → dose nutrients (A+B equal) ───────────────────────────
        if val_ec < self.range_ec[0]:
            self.logger.info(
                f"EC low: {val_ec:.3f} < {self.range_ec[0]:.3f} mS/cm — "
                f"dosing A+B ({self.output_ec_amount} {self.output_ec_type})"
            )
            self._dose_ec(val_ph, val_ec)
            # After dosing nutrients, wait for next cycle before touching pH
            return

        # ── 6. pH out of band ────────────────────────────────────────────────
        if val_ph > self.range_ph[1]:
            self.logger.info(
                f"pH high: {val_ph:.3f} > {self.range_ph[1]:.3f} — "
                f"dosing pH Down ({self.output_ph_amount} {self.output_ph_type})"
            )
            self._dose_ph_lower(val_ph, val_ec)
        elif val_ph < self.range_ph[0]:
            msg = (f"⚠️ [pH/EC] pH low: {val_ph:.2f} (min: {self.range_ph[0]:.2f})\n"
                   f"No pH Up — monitor manually.")
            self._tg_send_throttled('ph_low', msg)
            self.logger.warning(msg)

    # ── dosing helpers ─────────────────────────────────────────────────────────

    def _dose_ph_lower(self, val_ph: float, val_ec: float):
        """Dose pH Down and update totals. Checks daily limit first."""
        ph_type = 'vol' if self.output_ph_type == 'volume_ml' else 'sec'
        unit = 'ml' if ph_type == 'vol' else 'sec'

        # Calculate ml for this dose
        if ph_type == 'sec':
            ml_this_dose = self.output_ph_amount * (self.ml_per_min_ph / 60.0)
        else:
            ml_this_dose = self.output_ph_amount

        # Daily limit check
        self._reset_daily_if_needed()
        if self._daily_dosed['ph_ml'] + ml_this_dose > self.max_dose_ph_per_day_ml:
            msg = (
                f"\u26a0\ufe0f pH Down daglimiet bereikt: "
                f"{self._daily_dosed['ph_ml']:.1f}/{self.max_dose_ph_per_day_ml:.0f} ml. "
                f"Dosering OVERGESLAGEN. (pH={val_ph:.2f})"
            )
            self.logger.warning(msg)
            self._tg_send_throttled('dose_limit', msg)
            return

        # Always track both sec and ml totals
        if ph_type == 'sec':
            self.total['sec_ph_lower'] = self.set_custom_option(
                'sec_ph_lower',
                (self.get_custom_option('sec_ph_lower') or 0) + self.output_ph_amount)
        self.total['ml_ph_lower'] = self.set_custom_option(
            'ml_ph_lower',
            (self.get_custom_option('ml_ph_lower') or 0) + ml_this_dose)

        threading.Thread(
            target=self.control.output_on_off,
            args=(self.output_ph_lower_device_id, 'on'),
            kwargs={'output_type': ph_type,
                    'amount': self.output_ph_amount,
                    'output_channel': self._output_ph_lower_channel}
        ).start()

        # Track daily dose + log to InfluxDB for graphs
        self._daily_dosed['ph_ml'] += ml_this_dose
        self._save_daily_dosed()
        self._log_dose(0, ml_this_dose)

        self.logger.info(
            f"pH Down dosed: {ml_this_dose:.1f} ml ({self.output_ph_amount} {unit})  "
            f"(pH was {val_ph:.2f}, EC={val_ec:.3f})  "
            f"[dag: {self._daily_dosed['ph_ml']:.1f}/{self.max_dose_ph_per_day_ml:.0f} ml]"
        )

    def _dose_ec(self, val_ph: float, val_ec: float):
        """Dose nutrients A and B simultaneously. Checks daily limit first."""
        ec_type = 'vol' if self.output_ec_type == 'volume_ml' else 'sec'
        unit = 'ml' if ec_type == 'vol' else 'sec'

        # Calculate ml for this dose (per pump)
        amount = self.output_ec_amount
        if ec_type == 'sec':
            ml_this_dose = amount * (self.ml_per_min_ec / 60.0)
        else:
            ml_this_dose = amount

        # Daily limit check (against the higher of A or B)
        self._reset_daily_if_needed()
        peak_daily = max(self._daily_dosed['ec_a_ml'], self._daily_dosed['ec_b_ml'])
        if peak_daily + ml_this_dose > self.max_dose_ec_per_day_ml:
            msg = (
                f"\u26a0\ufe0f EC A+B daglimiet bereikt: "
                f"{peak_daily:.1f}/{self.max_dose_ec_per_day_ml:.0f} ml. "
                f"Dosering OVERGESLAGEN. (EC={val_ec:.3f} mS/cm)"
            )
            self.logger.warning(msg)
            self._tg_send_throttled('dose_limit', msg)
            return

        for pump_id, ch, key_sec, key_ml, daily_key, influx_ch in [
            (self.output_ec_a_device_id, self._output_ec_a_channel,
             'sec_ec_a', 'ml_ec_a', 'ec_a_ml', 1),
            (self.output_ec_b_device_id, self._output_ec_b_channel,
             'sec_ec_b', 'ml_ec_b', 'ec_b_ml', 2),
        ]:
            if not pump_id:
                continue
            # Always track both sec and ml totals
            if ec_type == 'sec':
                self.total[key_sec] = self.set_custom_option(
                    key_sec, (self.get_custom_option(key_sec) or 0) + amount)
            self.total[key_ml] = self.set_custom_option(
                key_ml, (self.get_custom_option(key_ml) or 0) + ml_this_dose)

            threading.Thread(
                target=self.control.output_on_off,
                args=(pump_id, 'on'),
                kwargs={'output_type': ec_type,
                        'amount': amount,
                        'output_channel': ch}
            ).start()

            # Track daily dose + log to InfluxDB for graphs
            self._daily_dosed[daily_key] += ml_this_dose
            self._save_daily_dosed()
            self._log_dose(influx_ch, ml_this_dose)

        self.logger.info(
            f"EC A+B dosed: {ml_this_dose:.1f} ml ({amount} {unit}) each  "
            f"(EC was {val_ec:.3f} mS/cm, pH={val_ph:.2f})  "
            f"[dag A: {self._daily_dosed['ec_a_ml']:.1f}/{self.max_dose_ec_per_day_ml:.0f} ml]"
        )

    # ── dose tracking & logging helpers ────────────────────────────────────────

    def _reset_daily_if_needed(self):
        """Reset per-day dose counters if date has changed."""
        today = date.today().isoformat()
        if self._daily_dosed.get('date') != today:
            self._daily_dosed = {
                'date': today, 'ph_ml': 0.0, 'ec_a_ml': 0.0, 'ec_b_ml': 0.0
            }
            self._save_daily_dosed()

    def _log_dose(self, channel: int, ml: float):
        """Write dosed ml to InfluxDB for dashboard graphs.

        Uses measure='volume' and unit='ml' to match the registered
        device_measurements channels (ch0=pH Down, ch1=EC A, ch2=EC B).
        """
        try:
            write_influxdb_value(
                self.unique_id, 'ml', ml,
                measure='volume', channel=channel
            )
        except Exception as e:
            self.logger.error(f"InfluxDB dose log error: {e}")

    # ── measurement helper ─────────────────────────────────────────────────────

    def _read(self, sensor: str):
        """Return last measurement value or None."""
        dev_id = getattr(self, f'select_measurement_{sensor}_device_id', None)
        meas_id = getattr(self, f'select_measurement_{sensor}_measurement_id', None)
        max_age = getattr(self, f'measurement_max_age_{sensor}', 360)
        if not dev_id or not meas_id:
            return None
        result = self.get_last_measurement(dev_id, meas_id, max_age=max_age)
        return result[1] if result else None

    # ── Telegram ──────────────────────────────────────────────────────────────

    def _tg_send_throttled(self, key: str, text: str):
        """Send Telegram message, but at most once per alert interval."""
        interval_sec = self.telegram_alert_interval_hours * 3600
        if self._tg_timers.get(key, 0) < time.time():
            self._tg_timers[key] = time.time() + interval_sec
            self._tg_send(text)

    def _tg_send(self, text: str):
        """Fire-and-forget Telegram POST."""
        token = (self.telegram_bot_token or '').strip()
        chat_id = (self.telegram_chat_id or '').strip()
        if not token or not chat_id:
            return
        threading.Thread(target=self._tg_post, args=(token, chat_id, text),
                         daemon=True).start()

    @staticmethod
    def _tg_post(token: str, chat_id: str, text: str):
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
                timeout=10
            )
            resp.raise_for_status()
        except Exception as exc:
            pass  # Never crash the regulation loop over a Telegram failure

    # ── persistent storage helper ─────────────────────────────────────────────

    def _load(self, key: str):
        v = self.get_custom_option(key)
        return float(v) if v is not None else None

    def _load_daily_dosed(self):
        """Load today's dose counters from DB, reset if date changed."""
        import json
        raw = self.get_custom_option('daily_dosed')
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if data.get('date') == date.today().isoformat():
                    return data
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        # New day or no data — start fresh
        fresh = {'date': date.today().isoformat(),
                 'ph_ml': 0.0, 'ec_a_ml': 0.0, 'ec_b_ml': 0.0}
        self._save_daily_dosed(fresh)
        return fresh

    def _save_daily_dosed(self, data=None):
        """Persist daily dose counters to DB."""
        import json
        if data is None:
            data = self._daily_dosed
        self.set_custom_option('daily_dosed', json.dumps(data))

    # ── custom command handlers ────────────────────────────────────────────────

    def reset_daily_dosed(self, args_dict):
        """Reset today's dose counters to 0 (pH, EC A, EC B)."""
        self._daily_dosed = {
            'date': date.today().isoformat(),
            'ph_ml': 0.0, 'ec_a_ml': 0.0, 'ec_b_ml': 0.0
        }
        self._save_daily_dosed()
        msg = 'Daily dose counters reset to 0 (pH, EC A, EC B).'
        self.logger.info(msg)
        return msg

    def reset_all_totals(self, args_dict):
        for k in list(self.total.keys()):
            self.total[k] = self.set_custom_option(k, 0)
        return 'All dosing totals reset to 0.'

    def reset_timer_all(self, args_dict):
        for k in list(self._tg_timers.keys()):
            self._tg_timers[k] = 0
        return 'All Telegram alert timers reset.'

    def send_test_telegram(self, args_dict):
        token = (self.telegram_bot_token or '').strip()
        chat_id = (self.telegram_chat_id or '').strip()
        if not token or not chat_id:
            return '❌ No Telegram token/chat_id configured.'
        self._tg_send(
            f'✅ [pH/EC Regulate] Test message from Mycodo.\n'
            f'pH band: {self.range_ph[0]:.2f}–{self.range_ph[1]:.2f}\n'
            f'EC band: {self.range_ec[0]:.2f}–{self.range_ec[1]:.2f} mS/cm'
        )
        return 'Test message sent to Telegram.'

    # ── status panel ──────────────────────────────────────────────────────────

    def function_status(self):
        self._reset_daily_if_needed()

        # Countdown to next check
        remaining = max(0, self.timer_loop - time.time())
        mins, secs = divmod(int(remaining), 60)
        countdown = f'{mins}m {secs:02d}s' if mins else f'{secs}s'

        return {
            'string_status': (
                f'&nbsp;<br><b>pH/EC Regulation (Telegram)</b>'
                f'<br>pH band: {self.range_ph[0]:.2f} – {self.range_ph[1]:.2f}'
                f'<br>EC band: {self.range_ec[0]:.3f} – {self.range_ec[1]:.3f} mS/cm'
                f'<br>⏱ Volgende check over <b>{countdown}</b>'
                f'<br>&nbsp;'
                f'<br><b>Vandaag gedoseerd</b>'
                f'<br>pH Down: {self._daily_dosed.get("ph_ml", 0):.1f} / '
                f'{self.max_dose_ph_per_day_ml:.0f} ml'
                f'<br>EC A: {self._daily_dosed.get("ec_a_ml", 0):.1f} / '
                f'{self.max_dose_ec_per_day_ml:.0f} ml'
                f'<br>EC B: {self._daily_dosed.get("ec_b_ml", 0):.1f} / '
                f'{self.max_dose_ec_per_day_ml:.0f} ml'
                f'<br>&nbsp;'
                f'<br><b>Totalen (all-time)</b>'
                f'<br>pH Down: {self.total.get("sec_ph_lower", 0):.1f} sec / '
                f'{self.total.get("ml_ph_lower", 0):.1f} ml'
                f'<br>EC A: {self.total.get("sec_ec_a", 0):.1f} sec / '
                f'{self.total.get("ml_ec_a", 0):.1f} ml'
                f'<br>EC B: {self.total.get("sec_ec_b", 0):.1f} sec / '
                f'{self.total.get("ml_ec_b", 0):.1f} ml'
            ),
            'error': []
        }

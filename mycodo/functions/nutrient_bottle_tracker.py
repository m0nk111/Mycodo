# coding=utf-8
#
#  nutrient_bottle_tracker.py - Nutrient Bottle Consumption Tracker
#
#  Copyright (C) 2015-2026 Kyle T. Gabriel <mycodo@kylegabriel.com>
#  Contributors: see AUTHORS file
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#
"""
Nutrient Bottle Consumption Tracker for Mycodo.

Tracks cumulative liquid dosed from up to 8 bottles/pumps by monitoring
Mycodo output runtime (seconds on) and multiplying by each pump's
calibrated flow rate (ml/min).  Displays colour-coded progress bars in
a dashboard widget and sends optional Telegram alerts when a bottle
drops below a configurable threshold.

Use Cases:
  - Hydroponic / aquaponic nutrient dosing monitoring
  - pH adjuster bottle tracking
  - Any peristaltic-pump dosing system where bottle level matters

Each pump slot is independently configurable with:
  - Friendly name
  - Output channel selection (any Mycodo output)
  - Bottle size (ml)
  - Calibrated flow rate (ml/min)

Bottle levels are persisted across restarts.  After physically
replacing a bottle, press the corresponding reset button.

Widget:
  The function_status() method returns an HTML block with a progress
  bar per pump so the widget is always up to date.
"""
import json
import time

import requests
from flask_babel import lazy_gettext

from mycodo.databases.models import CustomController
from mycodo.functions.base_function import AbstractFunction
from mycodo.utils.constraints_pass import constraints_pass_positive_value
from mycodo.utils.database import db_retrieve_table_daemon
from mycodo.utils.influx import add_measurements_influxdb
from mycodo.utils.influx import sum_past_seconds

# ---------------------------------------------------------------------------
# Maximum configurable pumps
# ---------------------------------------------------------------------------
MAX_PUMPS = 8


# ---------------------------------------------------------------------------
# Persistent widget status (visible even when the Function is deactivated)
# ---------------------------------------------------------------------------
def function_status_always(unique_id):
    """Return HTML status for the Function Status widget.

    Called from the ``/function_status_always/<unique_id>`` route so that
    the widget keeps displaying bottle levels while the Function is
    inactive.
    """
    try:
        custom_function = CustomController.query.filter(
            CustomController.unique_id == unique_id).first()
        if not custom_function:
            return {'error': ['Function not found']}

        # Parse custom_options into a dict
        opts = {}
        if custom_function.custom_options:
            try:
                raw = json.loads(custom_function.custom_options)
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict) and 'id' in item and 'value' in item:
                            opts[item['id']] = item['value']
                elif isinstance(raw, dict):
                    opts = raw
            except (json.JSONDecodeError, TypeError):
                pass

        def _f(key, default=0.0):
            try:
                return float(opts.get(key, default))
            except (ValueError, TypeError):
                return default

        def _s(key, default=''):
            return str(opts.get(key, default))

        num_pumps = int(_f('num_pumps', 1))

        # Load persisted bottle_data
        bottle_data = {}
        raw_bd = opts.get('_state_bottle_data')
        if raw_bd:
            try:
                bottle_data = json.loads(raw_bd) if isinstance(raw_bd, str) else raw_bd
            except (json.JSONDecodeError, TypeError):
                pass

        lines = ['<b>Nutrient Bottle Tracker</b><br>&nbsp;']

        for i in range(1, num_pumps + 1):
            name = _s(f'pump_{i}_name', f'Pump {i}') or f'Pump {i}'
            bottle_ml = _f(f'pump_{i}_bottle_ml', 1000.0)
            ml_per_min = _f(f'pump_{i}_ml_per_min', 48.0)

            key = str(i)
            placed_ts = bottle_data.get(key, {}).get('placed_ts', time.time())
            seconds_since = max(1, int(time.time() - placed_ts))

            # Resolve output UUID from select_channel value
            output_val = _s(f'pump_{i}_output', '')
            output_uuid = ''
            if output_val:
                try:
                    parsed = json.loads(output_val) if isinstance(output_val, str) else output_val
                    output_uuid = parsed.get('output_id', '') if isinstance(parsed, dict) else ''
                except (json.JSONDecodeError, TypeError):
                    output_uuid = str(output_val).split(',')[0] if ',' in str(output_val) else str(output_val)

            total_sec = 0.0
            if output_uuid:
                try:
                    total_sec = sum_past_seconds(
                        output_uuid, 's', 0,
                        seconds_since, measure='duration_time'
                    ) or 0.0
                except Exception:
                    total_sec = 0.0

            ml_dosed = total_sec * (ml_per_min / 60.0)
            ml_rem = max(0.0, bottle_ml - ml_dosed)
            pct = (ml_rem / bottle_ml * 100.0) if bottle_ml > 0 else 0.0

            # Color-coded progress bar
            if pct > 25:
                color = '#2ecc71'
            elif pct > 10:
                color = '#e67e22'
            else:
                color = '#e74c3c'

            filled = int(round(pct / 100.0 * 10))
            filled = max(0, min(10, filled))
            bar_text = '\u2593' * filled + '\u2591' * (10 - filled)

            lines.append(
                f'<br><span style="color:{color}"><b>P{i}</b> {name}</span>'
                f'<br>{bar_text} {pct:.0f}% &mdash; '
                f'{ml_rem:.0f}/{bottle_ml:.0f} ml'
            )

        return {
            'string_status': ''.join(lines),
            'error': []
        }

    except Exception as err:
        return {'error': [str(err)]}


# ---------------------------------------------------------------------------
# Build per-pump custom_options dynamically
# ---------------------------------------------------------------------------
def _build_pump_options():
    """Generate per-pump custom_options entries for up to MAX_PUMPS pumps."""
    opts = []
    for i in range(1, MAX_PUMPS + 1):
        opts.extend([
            {
                'type': 'message',
                'default_value': f'Pump {i} Configuration'
            },
            {
                'id': f'pump_{i}_name',
                'type': 'text',
                'default_value': '',
                'required': False,
                'name': lazy_gettext(f'Pump {i} Name'),
                'phrase': lazy_gettext(
                    f'Friendly name for pump {i} (e.g. "Nutrient A", "pH Down")')
            },
            {
                'id': f'pump_{i}_output',
                'type': 'select_channel',
                'default_value': '',
                'required': False,
                'options_select': ['Output_Channels'],
                'name': lazy_gettext(f'Pump {i} Output'),
                'phrase': lazy_gettext(
                    f'Select the output channel that drives pump {i}')
            },
            {
                'id': f'pump_{i}_bottle_ml',
                'type': 'float',
                'default_value': 1000.0,
                'required': False,
                'constraints_pass': constraints_pass_positive_value,
                'name': lazy_gettext(f'Pump {i} Bottle Size (ml)'),
                'phrase': lazy_gettext(
                    f'Total volume of the bottle connected to pump {i} in ml '
                    f'(e.g. 1000 for 1 L)')
            },
            {
                'id': f'pump_{i}_ml_per_min',
                'type': 'float',
                'default_value': 48.0,
                'required': False,
                'constraints_pass': constraints_pass_positive_value,
                'name': lazy_gettext(f'Pump {i} Flow Rate (ml/min)'),
                'phrase': lazy_gettext(
                    f'Calibrated flow rate of pump {i} in ml per minute')
            },
        ])
    return opts


# ---------------------------------------------------------------------------
# Build custom_commands (reset buttons) dynamically
# ---------------------------------------------------------------------------
def _build_custom_commands():
    """Generate per-pump reset buttons plus a Reset All button."""
    cmds = [
        {
            'id': 'reset_all',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Reset All Bottles'),
            'phrase': lazy_gettext(
                'Reset consumption counters for all pumps (as if all '
                'bottles were just replaced)')
        }
    ]
    for i in range(1, MAX_PUMPS + 1):
        cmds.append({
            'id': f'reset_pump_{i}',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext(f'Reset Bottle: Pump {i}'),
            'phrase': lazy_gettext(
                f'Reset the consumption counter for pump {i} after '
                f'replacing its bottle')
        })
    return cmds


# ---------------------------------------------------------------------------
# Measurements: one channel per pump = remaining ml
# ---------------------------------------------------------------------------
measurements_dict = {
    i: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': f'Pump {i + 1} remaining'
    }
    for i in range(MAX_PUMPS)
}


# ---------------------------------------------------------------------------
# FUNCTION_INFORMATION
# ---------------------------------------------------------------------------
FUNCTION_INFORMATION = {
    'function_name_unique': 'NUTRIENT_BOTTLE_TRACKER',
    'function_name': 'Nutrient Bottle Tracker',
    'function_name_short': 'Bottle Tracker',
    'function_library': '',
    'manufacturer': '',

    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': False,

    'function_status': function_status_always,

    'message': (
        'Tracks cumulative liquid dosed from up to 8 bottles by '
        'monitoring output runtime and multiplying by a calibrated '
        'flow rate (ml/min). Displays colour-coded progress bars in a '
        'widget and sends optional Telegram alerts when bottles run low.'
        '<br><br>'
        '<b>Setup:</b> Configure the number of pumps, assign an output '
        'channel to each, set bottle sizes and flow rates. Press a '
        'reset button whenever you replace a bottle.'
    ),

    'options_enabled': [
        'custom_options',
        'function_status'
    ],
    'options_disabled': ['measurements_select'],

    'custom_commands_message': (
        'Reset bottle counters after physically replacing bottles. '
        'Reset All resets every pump; individual buttons reset one pump.'
    ),
    'custom_commands': _build_custom_commands(),

    'custom_options': [
        # ── General ───────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'General Settings'
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Period (seconds)'),
            'phrase': lazy_gettext(
                'How often (in seconds) to recalculate consumption '
                'and store measurements')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': lazy_gettext('Start Offset (seconds)'),
            'phrase': lazy_gettext(
                'Delay after activation before the first calculation')
        },
        {
            'id': 'num_pumps',
            'type': 'integer',
            'default_value': 4,
            'required': True,
            'name': lazy_gettext('Number of Pumps'),
            'phrase': lazy_gettext(
                'Number of pumps/bottles to track (1-8)')
        },

        # ── Telegram ─────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'Telegram Notifications'
        },
        {
            'id': 'telegram_bot_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Telegram Bot Token'),
            'phrase': lazy_gettext(
                'Bot token from @BotFather (leave blank to disable alerts)')
        },
        {
            'id': 'telegram_chat_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Telegram Chat ID'),
            'phrase': lazy_gettext(
                'Numeric chat ID for Telegram notifications')
        },
        {
            'id': 'alert_threshold_pct',
            'type': 'float',
            'default_value': 15.0,
            'required': True,
            'name': lazy_gettext('Alert Threshold (%)'),
            'phrase': lazy_gettext(
                'Send an alert when remaining volume drops below this '
                'percentage (e.g. 15 = 15%)')
        },
        {
            'id': 'alert_interval_hours',
            'type': 'float',
            'default_value': 6.0,
            'required': True,
            'name': lazy_gettext('Alert Repeat Interval (hours)'),
            'phrase': lazy_gettext(
                'Minimum hours between repeated alerts for the same bottle')
        },

        # ── Per-pump options (generated) ─────────────────────────────
        {
            'type': 'message',
            'default_value': 'Pump / Bottle Configuration'
        },
        *_build_pump_options(),
    ]
}


# ===========================================================================
# CustomModule
# ===========================================================================

class CustomModule(AbstractFunction):
    """Nutrient bottle consumption tracker with Telegram alerts."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        # ── Defaults (overwritten by setup_custom_options) ────────────
        self.period = 300.0
        self.start_offset = 30
        self.num_pumps = 4
        self.telegram_bot_token = ''
        self.telegram_chat_id = ''
        self.alert_threshold_pct = 15.0
        self.alert_interval_hours = 6.0

        for i in range(1, MAX_PUMPS + 1):
            setattr(self, f'pump_{i}_name', '')
            setattr(self, f'pump_{i}_output', '')
            setattr(self, f'pump_{i}_bottle_ml', 1000.0)
            setattr(self, f'pump_{i}_ml_per_min', 48.0)

        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self):
        self.timer_loop = time.time() + self.start_offset
        self.logger.info(
            "Nutrient Bottle Tracker started — interval %ss, "
            "tracking %d pump(s)", self.period, self.num_pumps)

        # Ensure bottle_data store exists for each pump
        bottle_data = self._get_bottle_data()
        changed = False
        for i in range(1, self.num_pumps + 1):
            key = str(i)
            if key not in bottle_data:
                bottle_data[key] = {
                    'placed_ts': time.time(),
                    'last_alert_ts': 0
                }
                changed = True
        if changed:
            self._set_bottle_data(bottle_data)

        self._send_telegram(
            "*Nutrient Bottle Tracker started*\n"
            "Tracking {} pump(s), recalculating every {:.0f} min.".format(
                self.num_pumps, self.period / 60)
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def loop(self):
        if self.timer_loop > time.time():
            return
        while self.timer_loop < time.time():
            self.timer_loop += self.period

        bottle_data = self._get_bottle_data()
        measurement_dict = {}
        alerts = []

        for i in range(1, self.num_pumps + 1):
            idx = i - 1  # measurement channel index
            key = str(i)
            name = getattr(self, f'pump_{i}_name', '') or f'Pump {i}'
            bottle_ml = getattr(self, f'pump_{i}_bottle_ml', 1000.0)
            ml_per_min = getattr(self, f'pump_{i}_ml_per_min', 48.0)

            placed_ts = bottle_data.get(key, {}).get('placed_ts', time.time())
            seconds_since = max(1, int(time.time() - placed_ts))

            output_uuid = self._resolve_output_uuid(i)

            # Query total seconds the pump has been on since bottle placement
            total_sec = 0.0
            if output_uuid:
                try:
                    total_sec = sum_past_seconds(
                        output_uuid, 's', 0,
                        seconds_since, measure='duration_time'
                    ) or 0.0
                except Exception as exc:
                    self.logger.warning(
                        "InfluxDB query error for pump %d: %s", i, exc)

            ml_dosed = total_sec * (ml_per_min / 60.0)
            ml_remaining = max(0.0, bottle_ml - ml_dosed)
            pct_remaining = (
                (ml_remaining / bottle_ml * 100.0) if bottle_ml > 0 else 0.0
            )

            self.logger.debug(
                "Pump %d (%s): %.1f s on, %.1f ml dosed, "
                "%.1f ml remaining (%.1f%%)",
                i, name, total_sec, ml_dosed, ml_remaining, pct_remaining)

            measurement_dict[idx] = {
                'measurement': 'volume',
                'unit': 'ml',
                'value': round(ml_remaining, 1)
            }

            # Alert check
            last_alert = bottle_data.get(key, {}).get('last_alert_ts', 0)
            interval_sec = self.alert_interval_hours * 3600.0
            if (pct_remaining < self.alert_threshold_pct
                    and (time.time() - last_alert) > interval_sec):
                alerts.append((i, name, ml_remaining, pct_remaining, bottle_ml))
                bottle_data.setdefault(key, {})['last_alert_ts'] = time.time()

        # Persist updated alert timestamps
        self._set_bottle_data(bottle_data)

        # Store measurements in InfluxDB
        if measurement_dict:
            add_measurements_influxdb(self.unique_id, measurement_dict)

        # Send Telegram alerts for low bottles
        for (num, name, ml_rem, pct, bottle_ml) in alerts:
            bar = self._progress_bar_text(pct)
            msg = (
                f"*Bottle running low!*\n\n"
                f"Pump {num} — {name}\n"
                f"{bar} {pct:.1f}%\n"
                f"Remaining: *{ml_rem:.0f} ml* of {bottle_ml:.0f} ml\n\n"
                f"Threshold: {self.alert_threshold_pct:.0f}% — "
                f"replace the bottle and press Reset."
            )
            self._send_telegram(msg)
            self.logger.warning(
                "Low-bottle alert for Pump %d (%s): %.1f%% remaining",
                num, name, pct)

    # ------------------------------------------------------------------
    # Reset button handlers
    # ------------------------------------------------------------------

    def reset_all(self, args_dict=None):
        """Reset all bottle counters."""
        bottle_data = self._get_bottle_data()
        now = time.time()
        for i in range(1, self.num_pumps + 1):
            key = str(i)
            bottle_data[key] = {'placed_ts': now, 'last_alert_ts': 0}
        self._set_bottle_data(bottle_data)
        self._send_telegram(
            "*All bottles reset*\n"
            f"All {self.num_pumps} pump counters reset at "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}."
        )
        self.logger.info("All bottle counters reset")
        return "All bottle counters have been reset."

    def reset_pump_1(self, args_dict=None):
        return self._reset_pump(1)

    def reset_pump_2(self, args_dict=None):
        return self._reset_pump(2)

    def reset_pump_3(self, args_dict=None):
        return self._reset_pump(3)

    def reset_pump_4(self, args_dict=None):
        return self._reset_pump(4)

    def reset_pump_5(self, args_dict=None):
        return self._reset_pump(5)

    def reset_pump_6(self, args_dict=None):
        return self._reset_pump(6)

    def reset_pump_7(self, args_dict=None):
        return self._reset_pump(7)

    def reset_pump_8(self, args_dict=None):
        return self._reset_pump(8)

    def _reset_pump(self, num):
        """Reset the bottle placement timestamp for a single pump."""
        name = getattr(self, f'pump_{num}_name', '') or f'Pump {num}'
        bottle_ml = getattr(self, f'pump_{num}_bottle_ml', 1000.0)

        bottle_data = self._get_bottle_data()
        key = str(num)
        bottle_data[key] = {'placed_ts': time.time(), 'last_alert_ts': 0}
        self._set_bottle_data(bottle_data)

        msg = (
            f"*Bottle reset — Pump {num}*\n"
            f"{name}\n"
            f"New volume: {bottle_ml:.0f} ml\n"
            f"Clock restarted: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._send_telegram(msg)
        self.logger.info("Bottle reset for Pump %d (%s)", num, name)
        return (
            f"Pump {num} ({name}) bottle reset at "
            f"{time.strftime('%H:%M:%S')}."
        )

    # ------------------------------------------------------------------
    # Status panel (widget HTML)
    # ------------------------------------------------------------------

    def function_status(self):
        """Return HTML status for the dashboard widget."""
        lines = ['<b>Nutrient Bottle Tracker</b><br>&nbsp;']
        bottle_data = self._get_bottle_data()

        for i in range(1, self.num_pumps + 1):
            key = str(i)
            name = getattr(self, f'pump_{i}_name', '') or f'Pump {i}'
            bottle_ml = getattr(self, f'pump_{i}_bottle_ml', 1000.0)
            ml_per_min = getattr(self, f'pump_{i}_ml_per_min', 48.0)

            placed_ts = bottle_data.get(key, {}).get(
                'placed_ts', time.time())
            seconds_since = max(1, int(time.time() - placed_ts))

            output_uuid = self._resolve_output_uuid(i)

            total_sec = 0.0
            if output_uuid:
                try:
                    total_sec = sum_past_seconds(
                        output_uuid, 's', 0,
                        seconds_since, measure='duration_time'
                    ) or 0.0
                except Exception:
                    total_sec = 0.0

            ml_dosed = total_sec * (ml_per_min / 60.0)
            ml_rem = max(0.0, bottle_ml - ml_dosed)
            pct = (ml_rem / bottle_ml * 100.0) if bottle_ml > 0 else 0.0

            # Colour-coded progress bar
            if pct > 25:
                color = '#2ecc71'
            elif pct > 10:
                color = '#e67e22'
            else:
                color = '#e74c3c'

            bar = self._progress_bar_text(pct)

            lines.append(
                f'<br><span style="color:{color}"><b>P{i}</b> {name}</span>'
                f'<br>{bar} {pct:.0f}% &mdash; '
                f'{ml_rem:.0f}/{bottle_ml:.0f} ml'
            )

        return {
            'string_status': ''.join(lines),
            'error': []
        }

    # ==================================================================
    # Helper methods
    # ==================================================================

    def _resolve_output_uuid(self, pump_num):
        """Extract the output UUID from a select_channel value.

        ``select_channel`` stores its value as a comma-separated string
        ``"<device_id>,<channel_id>"`` or as a JSON dict.  We need only
        the device (output) UUID to query InfluxDB.
        """
        raw = getattr(self, f'pump_{pump_num}_output', '')
        if not raw:
            return ''

        # Try JSON dict format
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed.get('output_id', '')
            except (json.JSONDecodeError, TypeError):
                pass

        # Comma-separated format: "uuid,channel"
        raw_str = str(raw)
        if ',' in raw_str:
            return raw_str.split(',')[0].strip()

        return raw_str.strip()

    def _get_bottle_data(self):
        """Load per-pump bottle state from persistent custom options."""
        raw = self.get_custom_option('bottle_data', default_return=None)
        if raw:
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def _set_bottle_data(self, data):
        """Persist per-pump bottle state."""
        self.set_custom_option('bottle_data', json.dumps(data))

    def _send_telegram(self, message):
        """Send a Telegram message.  Fails silently if not configured."""
        token = (self.telegram_bot_token or '').strip()
        chat_id = (self.telegram_chat_id or '').strip()
        if not token or not chat_id:
            self.logger.debug(
                "Telegram not configured, skipping notification")
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(url, json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }, timeout=10)
            if not resp.ok:
                self.logger.warning(
                    "Telegram error: %s — %s",
                    resp.status_code, resp.text[:200])
        except Exception as exc:
            self.logger.warning("Telegram send failed: %s", exc)

    @staticmethod
    def _progress_bar_text(pct, length=10):
        """Generate a text progress bar: e.g. ``▓▓▓░░░░░░░``"""
        filled = int(round(pct / 100.0 * length))
        filled = max(0, min(length, filled))
        return '\u2593' * filled + '\u2591' * (length - filled)

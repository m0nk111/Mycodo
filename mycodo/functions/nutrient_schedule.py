# coding=utf-8
#
#  nutrient_schedule.py - Scheduled Nutrient Dosing Function
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
Scheduled Nutrient Dosing Function for Mycodo.

Automates daily dosing of up to 8 nutrient pumps according to a
user-defined weekly schedule. Designed for hydroponic / aquaponic systems
that follow a multi-week feeding chart (e.g. bloom cycle).

Strategy:
  - Doses 1/7 of the weekly amount each day at a configurable hour.
  - Week number is auto-calculated from a user-supplied start date.
  - First activation week can use a reduced percentage (gentle ramp-up).

Safety features:
  - Optional flow sensor pre-check with automatic retry/deferral.
  - Optional EC pre-check to refuse dosing above a threshold.
  - Configurable overdose safety factor with per-pump daily tracking.
  - Optional Telegram notifications for dose events and failures.

Schedule format (JSON):
  A single JSON text field maps week numbers to an array of ml/L values
  whose indices correspond to pumps 1-8.  Example for 4 pumps::

      {
        "1": [2.0, 2.0, 0.0, 2.0],
        "2": [2.0, 2.0, 2.0, 2.0],
        "3": [2.0, 2.0, 2.0, 2.0]
      }

  Weeks not listed default to 0 ml/L for all pumps (flush / off-cycle).
"""
import datetime
import json
import time

import requests
from flask_babel import lazy_gettext

from mycodo.databases.models import CustomController
from mycodo.functions.base_function import AbstractFunction
from mycodo.mycodo_client import DaemonControl
from mycodo.utils.database import db_retrieve_table_daemon


# ---------------------------------------------------------------------------
# Maximum number of configurable pumps
# ---------------------------------------------------------------------------
MAX_PUMPS = 8


# ---------------------------------------------------------------------------
# Persistent widget status (visible even when the Function is deactivated)
# ---------------------------------------------------------------------------
def function_status_always(unique_id):
    """Return HTML status for the Function Status widget.

    Called from the ``/function_status_always/<unique_id>`` route so that
    the widget keeps displaying information while the Function is inactive.
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

        def _s(key, default=''):
            return opts.get(key, default)

        def _f(key, default=0.0):
            try:
                return float(opts.get(key, default))
            except (ValueError, TypeError):
                return default

        # Resolve state keys
        start_date = _s('bloom_start_date', '')
        reservoir = _f('reservoir_liters', 0)
        dose_hour = int(_f('dose_hour', 8))
        num_pumps = int(_f('num_pumps', 1))
        first_week_pct = _f('first_week_pct', 50.0)
        last_dose = _s('_state_last_dose_date', '')
        activation_date = _s('_state_activation_date', '')
        first_week_done = _s('_state_first_week_done', '')

        # Bloom week calculation
        week = 0
        if start_date:
            try:
                sd = datetime.date.fromisoformat(start_date)
                delta = (datetime.date.today() - sd).days
                week = max(1, (delta // 7) + 1)
            except (ValueError, TypeError):
                pass

        pct = 100.0 if first_week_done else first_week_pct

        # Parse schedule
        schedule = {}
        sched_json = _s('schedule_json', '{}')
        try:
            schedule = json.loads(sched_json) if isinstance(sched_json, str) else {}
        except (json.JSONDecodeError, TypeError):
            pass

        week_sched = schedule.get(str(week), [0.0] * MAX_PUMPS)

        # Doses today
        doses_today_json = _s('_state_doses_today', '{}')
        try:
            doses_today = json.loads(doses_today_json) if isinstance(doses_today_json, str) else {}
        except (json.JSONDecodeError, TypeError):
            doses_today = {}

        activated = bool(custom_function.is_activated) if hasattr(
            custom_function, 'is_activated') else False
        badge = (
            '<span style="color:#0a0;font-weight:bold;">&#9679; ACTIVE</span>'
            if activated else
            '<span style="color:#a00;font-weight:bold;">&#9679; INACTIVE</span>'
        )

        lines = [
            badge,
            f'<br><b>Cycle Week:</b> {week} &nbsp;|&nbsp; '
            f'<b>Dose %:</b> {pct:.0f}% &nbsp;|&nbsp; '
            f'<b>Reservoir:</b> {reservoir:.0f} L',
            f'<br><b>Dose Hour:</b> {dose_hour:02d}:00 &nbsp;|&nbsp; '
            f'<b>Last Dosed:</b> {last_dose or "never"}',
            '<br><br><b>Today&#39;s Schedule (ml/day per pump)</b>',
        ]
        for i in range(min(num_pumps, MAX_PUMPS)):
            name = _s(f'pump_{i+1}_name', f'Pump {i+1}')
            ml_l = week_sched[i] if i < len(week_sched) else 0.0
            try:
                ml_l = float(ml_l)
            except (ValueError, TypeError):
                ml_l = 0.0
            ml_day = (ml_l * reservoir / 7.0) * (pct / 100.0)
            already = doses_today.get(str(i), 0.0)
            try:
                already = float(already)
            except (ValueError, TypeError):
                already = 0.0
            if ml_day > 0:
                lines.append(
                    f'<br>&bull; {name}: {ml_day:.1f} ml '
                    f'(dosed {already:.1f} ml)')
            else:
                lines.append(f'<br>&bull; {name}: &mdash;')

        html = ''.join(lines)
        return {'string_status': html, 'error': []}
    except Exception as err:
        return {'error': [str(err)]}


# ---------------------------------------------------------------------------
# Build custom_options dynamically for up to MAX_PUMPS pumps
# ---------------------------------------------------------------------------
def _build_pump_options():
    """Generate per-pump custom_options entries."""
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
                'name': f'Pump {i} Name',
                'phrase': f'Friendly name for pump {i} (e.g. "Nutrient A", "CalMag")'
            },
            {
                'id': f'pump_{i}_output',
                'type': 'select_channel',
                'default_value': '',
                'required': False,
                'options_select': ['Output_Channels'],
                'name': f'Pump {i} Output',
                'phrase': f'Select the output channel that drives pump {i}'
            },
            {
                'id': f'pump_{i}_ml_per_min',
                'type': 'float',
                'default_value': 48.0,
                'required': False,
                'name': f'Pump {i} Flow Rate (ml/min)',
                'phrase': f'Calibrated flow rate of pump {i} in ml per minute'
            },
        ])
    return opts


# ---------------------------------------------------------------------------
# FUNCTION_INFORMATION
# ---------------------------------------------------------------------------
FUNCTION_INFORMATION = {
    'function_name_unique': 'NUTRIENT_SCHEDULE',
    'function_name': 'Scheduled Nutrient Dosing',
    'function_name_short': 'Nutrient Schedule',
    'function_library': '',
    'manufacturer': '',

    'function_status': function_status_always,

    'message': (
        'Automates daily dosing of up to 8 nutrient pumps according to a '
        'weekly feeding-chart schedule. Designed for hydroponic or aquaponic '
        'systems following a multi-week bloom / grow cycle.'
        '<br><br><b>How it works:</b> Each day at the configured hour, the '
        'function calculates the current cycle week from the start date, '
        'looks up the schedule, and doses 1/7 of the weekly amount per pump.'
        '<br><b>Schedule JSON</b>: A JSON object mapping week number (string) '
        'to an array of ml/L values per pump index.  Example for 3 pumps:<br>'
        '<code>{"1": [2.0, 2.0, 0.0], "2": [2.0, 2.0, 2.0]}</code>'
        '<br>Unmapped weeks default to 0 ml/L (flush / rest).'
        '<br><b>Safety</b>: Optional flow check, EC pre-check, per-pump '
        'overdose protection, and Telegram notifications.'
    ),

    'options_enabled': [
        'custom_options',
        'function_status'
    ],
    'options_disabled': ['measurements_select'],

    # ------------------------------------------------------------------
    # Custom commands
    # ------------------------------------------------------------------
    'custom_commands_message': (
        'Manually trigger dosing, display the current schedule, or reset '
        'the first-week ramp-up flag.'
    ),
    'custom_commands': [
        {
            'id': 'dose_now',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Dose Now'),
            'phrase': lazy_gettext(
                'Immediately dose the daily amount (bypasses timer and flow check)')
        },
        {
            'id': 'status_now',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Show Schedule'),
            'phrase': lazy_gettext(
                'Display the current week schedule and ml/day per pump')
        },
        {
            'id': 'reset_first_week',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Reset First-Week Flag'),
            'phrase': lazy_gettext(
                'Clear the first-week-done state so the next dose uses '
                'the reduced first-week percentage again')
        },
    ],

    # ------------------------------------------------------------------
    # Custom options
    # ------------------------------------------------------------------
    'custom_options': [
        # ── General ───────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'General Settings'
        },
        {
            'id': 'bloom_start_date',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Cycle Start Date (YYYY-MM-DD)'),
            'phrase': lazy_gettext(
                'The date when the grow/bloom cycle started. '
                'Used to auto-calculate the current week number.')
        },
        {
            'id': 'reservoir_liters',
            'type': 'float',
            'default_value': 40.0,
            'required': True,
            'name': "{} ({})".format(
                lazy_gettext('Reservoir Volume'), lazy_gettext('Liters')),
            'phrase': lazy_gettext(
                'Current volume of the nutrient reservoir in liters')
        },
        {
            'id': 'dose_hour',
            'type': 'integer',
            'default_value': 8,
            'required': True,
            'name': lazy_gettext('Dose Hour (0-23)'),
            'phrase': lazy_gettext(
                'Hour of the day (server time) to perform automatic dosing')
        },
        {
            'id': 'first_week_pct',
            'type': 'float',
            'default_value': 50.0,
            'required': True,
            'name': lazy_gettext('First Week Percentage (%)'),
            'phrase': lazy_gettext(
                'Dose percentage for the first activation week (e.g. 50 = 50%)')
        },
        {
            'id': 'num_pumps',
            'type': 'integer',
            'default_value': 4,
            'required': True,
            'name': lazy_gettext('Number of Pumps (1-8)'),
            'phrase': lazy_gettext(
                'How many nutrient pumps to use (1 to 8)')
        },

        # ── Schedule ──────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': (
                'Schedule JSON — Maps week number to an array of ml/L values '
                'per pump index.  Example for 4 pumps, 3 weeks:<br>'
                '<code>{"1": [2.0, 2.0, 0.0, 2.0], '
                '"2": [2.0, 2.0, 2.0, 2.0], '
                '"3": [2.0, 2.0, 2.0, 2.0]}</code><br>'
                'Weeks not listed default to all zeros (flush/rest).'
            )
        },
        {
            'id': 'schedule_json',
            'type': 'text',
            'default_value': '{}',
            'required': True,
            'name': lazy_gettext('Schedule JSON'),
            'phrase': lazy_gettext(
                'JSON object: {"week": [ml/L pump1, ml/L pump2, ...]}')
        },

        # ── EC Safety ─────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'EC Safety (optional)'
        },
        {
            'id': 'ec_check_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable EC Pre-Check'),
            'phrase': lazy_gettext(
                'When enabled, dosing is refused if EC exceeds the threshold')
        },
        {
            'id': 'select_measurement_ec',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'required': False,
            'name': lazy_gettext('EC Measurement'),
            'phrase': lazy_gettext(
                'Select the EC measurement input for pre-dose safety check')
        },
        {
            'id': 'ec_max_age',
            'type': 'integer',
            'default_value': 600,
            'required': True,
            'name': "{}: {} ({})".format(
                lazy_gettext('EC'), lazy_gettext('Max Age'),
                lazy_gettext('Seconds')),
            'phrase': lazy_gettext(
                'Maximum age (seconds) of the EC reading to consider valid')
        },
        {
            'id': 'max_ec_before_dose',
            'type': 'float',
            'default_value': 2000.0,
            'required': True,
            'name': lazy_gettext('Max EC Before Dose (uS/cm)'),
            'phrase': lazy_gettext(
                'Refuse dosing when EC is above this value')
        },

        # ── Overdose Protection ───────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'Overdose Protection'
        },
        {
            'id': 'overdose_safety_factor',
            'type': 'float',
            'default_value': 1.5,
            'required': True,
            'name': lazy_gettext('Overdose Safety Factor'),
            'phrase': lazy_gettext(
                'Maximum multiple of the scheduled daily dose per pump. '
                'E.g. 1.5 = pump will not exceed 150% of planned dose per day.')
        },

        # ── Flow Safety ───────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'Flow Safety (optional)'
        },
        {
            'id': 'flow_check_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Flow Check'),
            'phrase': lazy_gettext(
                'Refuse dosing when water circulation flow is below minimum')
        },
        {
            'id': 'select_measurement_flow',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'required': False,
            'name': lazy_gettext('Flow Measurement'),
            'phrase': lazy_gettext(
                'Select the flow rate measurement input')
        },
        {
            'id': 'flow_max_age',
            'type': 'integer',
            'default_value': 120,
            'required': True,
            'name': "{}: {} ({})".format(
                lazy_gettext('Flow'), lazy_gettext('Max Age'),
                lazy_gettext('Seconds')),
            'phrase': lazy_gettext(
                'Maximum age of the flow measurement in seconds')
        },
        {
            'id': 'min_flow_rate',
            'type': 'float',
            'default_value': 0.05,
            'required': True,
            'name': lazy_gettext('Minimum Flow Rate (L/min)'),
            'phrase': lazy_gettext(
                'Minimum flow rate to consider water as circulating')
        },
        {
            'id': 'dose_retry_minutes',
            'type': 'integer',
            'default_value': 15,
            'required': True,
            'name': lazy_gettext('Flow Retry Interval (minutes)'),
            'phrase': lazy_gettext(
                'Minutes to wait between retries when flow is insufficient')
        },
        {
            'id': 'dose_max_retries',
            'type': 'integer',
            'default_value': 8,
            'required': True,
            'name': lazy_gettext('Max Flow Retries'),
            'phrase': lazy_gettext(
                'Maximum number of retry attempts (e.g. 8 x 15 min = 2 hours)')
        },

        # ── Telegram ──────────────────────────────────────────────────
        {
            'type': 'message',
            'default_value': 'Telegram Notifications (optional)'
        },
        {
            'id': 'telegram_bot_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Telegram Bot Token'),
            'phrase': lazy_gettext('Bot token from @BotFather')
        },
        {
            'id': 'telegram_chat_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Telegram Chat ID'),
            'phrase': lazy_gettext(
                'Chat ID to send notifications to')
        },

        # ── Pump configurations (generated) ───────────────────────────
        {
            'type': 'message',
            'default_value': (
                'Pump Configuration — Configure each pump below. Only pumps '
                'up to the "Number of Pumps" setting will be used. The pump '
                'index (1-8) corresponds to the array position in the '
                'Schedule JSON.'
            )
        },
    ] + _build_pump_options(),
}


# ===========================================================================
# CustomModule
# ===========================================================================
class CustomModule(AbstractFunction):
    """Scheduled nutrient dosing with per-pump weekly schedule."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        # ── Defaults (overwritten by setup_custom_options) ────────────
        self.bloom_start_date = ''
        self.reservoir_liters = 40.0
        self.dose_hour = 8
        self.first_week_pct = 50.0
        self.num_pumps = 4
        self.schedule_json = '{}'

        self.ec_check_enabled = False
        self.select_measurement_ec_device_id = None
        self.select_measurement_ec_measurement_id = None
        self.ec_max_age = 600
        self.max_ec_before_dose = 2000.0

        self.overdose_safety_factor = 1.5

        self.flow_check_enabled = False
        self.select_measurement_flow_device_id = None
        self.select_measurement_flow_measurement_id = None
        self.flow_max_age = 120
        self.min_flow_rate = 0.05
        self.dose_retry_minutes = 15
        self.dose_max_retries = 8

        self.telegram_bot_token = ''
        self.telegram_chat_id = ''

        # Per-pump defaults
        for i in range(1, MAX_PUMPS + 1):
            setattr(self, f'pump_{i}_name', '')
            setattr(self, f'pump_{i}_output_device_id', None)
            setattr(self, f'pump_{i}_output_channel_id', None)
            setattr(self, f'pump_{i}_ml_per_min', 48.0)

        # Apply saved options
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        # Parse schedule
        self.schedule = {}
        try:
            self.schedule = json.loads(self.schedule_json) \
                if isinstance(self.schedule_json, str) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.error("Invalid schedule JSON; defaulting to empty")

        # Clamp num_pumps
        self.num_pumps = max(1, min(int(self.num_pumps), MAX_PUMPS))

        # Resolve output channels
        self._pump_channels = []
        for i in range(1, self.num_pumps + 1):
            dev_id = getattr(self, f'pump_{i}_output_device_id', None)
            ch_id = getattr(self, f'pump_{i}_output_channel_id', None)
            channel = self.get_output_channel_from_channel_id(ch_id) \
                if ch_id else 0
            self._pump_channels.append({
                'index': i,
                'name': getattr(self, f'pump_{i}_name', '') or f'Pump {i}',
                'device_id': dev_id,
                'channel': channel,
                'ml_per_min': getattr(self, f'pump_{i}_ml_per_min', 48.0)
                              or 48.0,
            })

        # ── Persistent state ──────────────────────────────────────────
        self._activation_date = (
            self._load_state('activation_date')
            or datetime.date.today().isoformat()
        )
        if not self._load_state('activation_date'):
            self._save_state('activation_date', self._activation_date)

        self._last_dose_date = self._load_state('last_dose_date') or ''

        self._doses_today = self._load_state('doses_today') or {}
        if self._doses_today.get('date') != datetime.date.today().isoformat():
            self._doses_today = {'date': datetime.date.today().isoformat()}
            self._save_state('doses_today', self._doses_today)

        self.control = DaemonControl()

        # Flow-deferral runtime state
        self._deferred_count = 0
        self._deferred_next = 0.0
        self._deferred_date = ''

        self.logger.info(
            "Nutrient Schedule started — week %d, reservoir %.0fL, "
            "dose at %02d:00, first-week %.0f%%, %d pumps",
            self._cycle_week(), self.reservoir_liters,
            self.dose_hour, self.first_week_pct, self.num_pumps)

    # ==================================================================
    # Main loop
    # ==================================================================

    def loop(self):
        """Check every cycle if it is time to dose (with deferral retry)."""
        now = datetime.datetime.now()
        today_str = datetime.date.today().isoformat()

        # Already dosed today
        if self._last_dose_date == today_str:
            return

        # Reset deferral counters on new day
        if self._deferred_date != today_str:
            self._deferred_count = 0
            self._deferred_next = 0.0
            self._deferred_date = today_str

        # Determine if we should trigger dosing
        trigger = False
        if now.hour >= self.dose_hour and self._deferred_count == 0:
            trigger = True
        elif self._deferred_count > 0 and time.time() >= self._deferred_next:
            trigger = True

        if not trigger:
            return

        result = self._do_dose()
        if result == 'DEFERRED':
            self._deferred_count += 1
            if self._deferred_count >= self.dose_max_retries:
                msg = (
                    f"Dosing CANCELLED after {self._deferred_count} attempts "
                    f"— no water flow detected. Check the circulation pump!"
                )
                self.logger.error(msg)
                self._tg_send(msg)
                self._last_dose_date = today_str
                self._save_state('last_dose_date', today_str)
            else:
                self._deferred_next = (
                    time.time() + self.dose_retry_minutes * 60
                )
                msg = (
                    f"Dosing deferred (attempt {self._deferred_count}/"
                    f"{self.dose_max_retries}) — no flow. "
                    f"Next retry in {self.dose_retry_minutes} min."
                )
                self.logger.warning(msg)
                if self._deferred_count == 1:
                    self._tg_send(msg)

    # ==================================================================
    # Custom commands
    # ==================================================================

    def dose_now(self, args_dict):
        """Button: dose immediately (bypass timer and flow check)."""
        return self._do_dose(force=True)

    def status_now(self, args_dict):
        """Button: show current week schedule."""
        week = self._cycle_week()
        pct = self._get_dose_pct()
        liters = self.reservoir_liters
        week_sched = self.schedule.get(str(week), [0.0] * MAX_PUMPS)

        lines = [
            f"Week {week} schedule ({pct:.0f}% dose, "
            f"{liters:.0f}L reservoir)\n"
        ]
        for pump in self._pump_channels:
            idx = pump['index'] - 1
            ml_l = float(week_sched[idx]) if idx < len(week_sched) else 0.0
            ml_day = (ml_l * liters / 7.0) * (pct / 100.0)
            if ml_day > 0:
                sec = (ml_day / pump['ml_per_min']) * 60.0
                lines.append(
                    f"  {pump['name']}: {ml_day:.1f} ml/day ({sec:.1f}s)")
            else:
                lines.append(
                    f"  {pump['name']}: — (not scheduled week {week})")
        lines.append(
            f"\nLast dosed: {self._last_dose_date or 'never'}")
        return "\n".join(lines)

    def reset_first_week(self, args_dict):
        """Button: clear the first-week-done flag."""
        self._save_state('first_week_done', '')
        msg = "First-week flag reset. Next dose will use reduced percentage."
        self.logger.info(msg)
        return msg

    # ==================================================================
    # Dosing logic
    # ==================================================================

    def _do_dose(self, force=False):
        """Dose all configured pumps according to today's schedule.

        Returns:
            'DEFERRED' if flow check failed and retry is appropriate.
            Otherwise a summary string.
        """
        week = self._cycle_week()
        pct = self._get_dose_pct()
        liters = self.reservoir_liters
        today_str = datetime.date.today().isoformat()

        week_sched = self.schedule.get(str(week), [0.0] * MAX_PUMPS)

        # ── Flow pre-check ────────────────────────────────────────────
        if self.flow_check_enabled and not force:
            flow_rate = self._read_flow()
            if flow_rate is None or flow_rate < self.min_flow_rate:
                flow_str = (
                    f"{flow_rate:.3f}" if flow_rate is not None else "no data"
                )
                self.logger.warning(
                    "Flow check FAILED: %s L/min (min: %.3f). "
                    "Dosing deferred.", flow_str, self.min_flow_rate)
                return 'DEFERRED'
            self.logger.info("Flow check OK: %.3f L/min", flow_rate)

        # ── EC pre-check ──────────────────────────────────────────────
        ec_value = self._read_ec() if self.ec_check_enabled else None
        if ec_value is not None and ec_value > self.max_ec_before_dose:
            msg = (
                f"EC too high: {ec_value:.0f} uS/cm "
                f"(max {self.max_ec_before_dose:.0f}). Dosing REFUSED."
            )
            self.logger.warning(msg)
            self._tg_send(msg)
            return msg
        if ec_value is not None:
            self.logger.info("EC pre-check OK: %.0f uS/cm", ec_value)

        # ── Reset daily tracker if new day ────────────────────────────
        if self._doses_today.get('date') != today_str:
            self._doses_today = {'date': today_str}

        dosed = []
        skipped = []

        for pump in self._pump_channels:
            idx = pump['index'] - 1
            ml_per_liter = float(
                week_sched[idx]) if idx < len(week_sched) else 0.0
            if ml_per_liter <= 0:
                skipped.append(pump['name'])
                continue

            if not pump['device_id']:
                skipped.append(f"{pump['name']} (no output configured)")
                continue

            ml_day = (ml_per_liter * liters / 7.0) * (pct / 100.0)
            ml_per_min = pump['ml_per_min']
            duration_sec = (ml_day / ml_per_min) * 60.0

            if duration_sec < 0.5:
                skipped.append(f"{pump['name']} (<0.5s)")
                continue

            # ── Per-pump daily limit ──────────────────────────────────
            pump_key = str(idx)
            already_dosed = float(self._doses_today.get(pump_key, 0.0))
            max_ml_today = ml_day * self.overdose_safety_factor
            if already_dosed >= max_ml_today:
                msg = (
                    f"{pump['name']}: already {already_dosed:.1f}ml "
                    f"(max {max_ml_today:.1f}ml). Skipped."
                )
                skipped.append(msg)
                self.logger.warning("Overdose guard: %s", msg)
                continue

            # Clamp to remaining headroom
            remaining = max_ml_today - already_dosed
            if ml_day > remaining:
                self.logger.info(
                    "%s: clamped %.1f -> %.1f ml (headroom)",
                    pump['name'], ml_day, remaining)
                ml_day = remaining
                duration_sec = (ml_day / ml_per_min) * 60.0

            try:
                self.control.output_on_off(
                    pump['device_id'],
                    'on',
                    output_type='sec',
                    amount=round(duration_sec, 1),
                    output_channel=pump['channel']
                )
                dosed.append(
                    f"{pump['name']}: {ml_day:.1f}ml ({duration_sec:.1f}s)")
                self.logger.info(
                    "Dosed %s: %.1f ml (%.1f sec) — week %d, %.0f%%",
                    pump['name'], ml_day, duration_sec, week, pct)

                # Track dose
                self._doses_today[pump_key] = already_dosed + ml_day
                self._save_state('doses_today', self._doses_today)

                # Wait for pump to finish + settling gap
                time.sleep(duration_sec + 2)
            except Exception as e:
                self.logger.error("Dose error %s: %s", pump['name'], e)

        # Mark day complete
        self._last_dose_date = today_str
        self._save_state('last_dose_date', today_str)

        # Mark first week done after first successful dose
        if not self._load_state('first_week_done'):
            self._save_state('first_week_done', 'yes')

        # ── Summary ───────────────────────────────────────────────────
        ec_str = f" | EC {ec_value:.0f} uS/cm" if ec_value is not None else ""
        msg = (
            f"[Nutrient Schedule] Daily dose complete\n"
            f"Week {week} | {pct:.0f}% dose | "
            f"{liters:.0f}L{ec_str}\n\n"
        )
        if dosed:
            msg += "Dosed:\n" + "\n".join(f"  + {d}" for d in dosed)
        if skipped:
            msg += "\n\nSkipped:\n" + "\n".join(f"  - {s}" for s in skipped)
        self._tg_send(msg)
        self.logger.info(
            "Daily dose complete — week %d, %.0f%%", week, pct)
        return msg

    # ==================================================================
    # Measurement helpers
    # ==================================================================

    def _read_ec(self):
        """Read the last EC measurement. Returns float (uS/cm) or None."""
        dev_id = getattr(self, 'select_measurement_ec_device_id', None)
        meas_id = getattr(self, 'select_measurement_ec_measurement_id', None)
        if not dev_id or not meas_id:
            self.logger.debug(
                "EC measurement not configured — skipping EC check")
            return None
        try:
            last = self.get_last_measurement(
                dev_id, meas_id, max_age=self.ec_max_age)
            if last:
                return float(last[1])
            self.logger.warning(
                "EC read returned None (no data within %ds)", self.ec_max_age)
            return None
        except Exception as e:
            self.logger.error("EC read error: %s", e)
            return None

    def _read_flow(self):
        """Read the last flow measurement. Returns float (L/min) or None."""
        dev_id = getattr(
            self, 'select_measurement_flow_device_id', None)
        meas_id = getattr(
            self, 'select_measurement_flow_measurement_id', None)
        if not dev_id or not meas_id:
            self.logger.debug(
                "Flow measurement not configured — skipping flow check")
            return None
        try:
            last = self.get_last_measurement(
                dev_id, meas_id, max_age=self.flow_max_age)
            if last:
                return float(last[1])
            self.logger.warning(
                "Flow read returned None (no data within %ds)",
                self.flow_max_age)
            return None
        except Exception as e:
            self.logger.error("Flow read error: %s", e)
            return None

    # ==================================================================
    # Calculation helpers
    # ==================================================================

    def _cycle_week(self):
        """Return current cycle week (1-based) from bloom_start_date."""
        try:
            start = datetime.date.fromisoformat(self.bloom_start_date)
            delta = (datetime.date.today() - start).days
            return max(1, (delta // 7) + 1)
        except (ValueError, TypeError):
            return 1

    def _get_dose_pct(self):
        """Dose percentage: first_week_pct initially, 100% after first dose."""
        if self._load_state('first_week_done'):
            return 100.0
        return self.first_week_pct

    # ==================================================================
    # Persistent state helpers
    # ==================================================================

    def _load_state(self, key):
        """Load a state value from custom_options in the database."""
        try:
            func = db_retrieve_table_daemon(
                CustomController, unique_id=self.unique_id)
            opts = {}
            if func and func.custom_options:
                raw = json.loads(func.custom_options)
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict) and 'id' in item:
                            opts[item['id']] = item.get('value')
                elif isinstance(raw, dict):
                    opts = raw
            return opts.get(f'_state_{key}')
        except Exception:
            return None

    def _save_state(self, key, value):
        """Persist a state value into custom_options in the database."""
        try:
            import sqlite3
            db_path = '/opt/Mycodo/databases/mycodo.db'
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            cur.execute(
                "SELECT custom_options FROM custom_controller "
                "WHERE unique_id=?", (self.unique_id,))
            row = cur.fetchone()
            if row:
                raw = json.loads(row[0]) if row[0] else {}
                if isinstance(raw, list):
                    # List-based storage: find or append
                    found = False
                    for item in raw:
                        if (isinstance(item, dict)
                                and item.get('id') == f'_state_{key}'):
                            item['value'] = value
                            found = True
                            break
                    if not found:
                        raw.append({
                            'id': f'_state_{key}', 'value': value
                        })
                    new_opts = json.dumps(raw)
                elif isinstance(raw, dict):
                    raw[f'_state_{key}'] = value
                    new_opts = json.dumps(raw)
                else:
                    new_opts = json.dumps(
                        {f'_state_{key}': value})
                cur.execute(
                    "UPDATE custom_controller SET custom_options=? "
                    "WHERE unique_id=?", (new_opts, self.unique_id))
                con.commit()
            con.close()
        except Exception as e:
            self.logger.error("_save_state error: %s", e)

    # ==================================================================
    # Telegram helper
    # ==================================================================

    def _tg_send(self, text):
        """Send a Telegram notification (if configured)."""
        token = (self.telegram_bot_token or '').strip()
        chat_id = (self.telegram_chat_id or '').strip()
        if not token or not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    'chat_id': chat_id,
                    'text': text,
                    'parse_mode': 'Markdown'
                },
                timeout=10
            )
        except Exception as e:
            self.logger.error("Telegram error: %s", e)

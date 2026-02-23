# coding=utf-8
#
#  regulate_ph_ec_v2.py - Regulate pH and EC with Telegram notifications,
#                         water level safety lock, daily dose limits,
#                         InfluxDB dose logging, and sensor sanity checks
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
import datetime
import json
import threading
import time

import requests
from flask_babel import lazy_gettext

from mycodo.databases.models import CustomController
from mycodo.functions.base_function import AbstractFunction
from mycodo.mycodo_client import DaemonControl
from mycodo.utils.constraints_pass import constraints_pass_positive_value
from mycodo.utils.database import db_retrieve_table_daemon
from mycodo.utils.influx import write_influxdb_value


def function_status_always(unique_id):
    """Return status HTML even when the Function is deactivated.

    This is called from the /function_status_always/<unique_id> route
    and provides persistent display in the Function Status widget.
    """
    try:
        custom_function = CustomController.query.filter(
            CustomController.unique_id == unique_id).first()
        if not custom_function:
            return {'error': ['Function not found']}

        # Reconstruct minimal state from persisted custom_options
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

        def _opt(key, default=0):
            val = opts.get(key, default)
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        setpoint_ph = _opt('setpoint_ph', 5.85)
        hysteresis_ph = _opt('hysteresis_ph', 0.35)
        setpoint_ec = _opt('setpoint_ec', 150.0)
        hysteresis_ec = _opt('hysteresis_ec', 50.0)
        max_ph_ml_day = _opt('max_ph_ml_per_day', 50.0)
        max_ec_ml_day = _opt('max_ec_ml_per_day', 100.0)

        total_sec_ph_raise = _opt('sec_ph_raise')
        total_sec_ph_lower = _opt('sec_ph_lower')
        total_ml_ph_raise = _opt('ml_ph_raise')
        total_ml_ph_lower = _opt('ml_ph_lower')
        total_sec_ec_a = _opt('sec_ec_a')
        total_sec_ec_b = _opt('sec_ec_b')
        total_sec_ec_c = _opt('sec_ec_c')
        total_sec_ec_d = _opt('sec_ec_d')
        total_ml_ec_a = _opt('ml_ec_a')
        total_ml_ec_b = _opt('ml_ec_b')
        total_ml_ec_c = _opt('ml_ec_c')
        total_ml_ec_d = _opt('ml_ec_d')

        daily_json_str = opts.get('daily_dosed_json', '{}')
        try:
            daily = json.loads(daily_json_str) if isinstance(daily_json_str, str) else {}
        except (json.JSONDecodeError, TypeError):
            daily = {}

        today_str = datetime.date.today().isoformat()
        day_data = daily.get(today_str, {})
        daily_ph = day_data.get('ph_ml', 0)
        daily_ec = day_data.get('ec_ml', 0)

        ph_lo = setpoint_ph - hysteresis_ph
        ph_hi = setpoint_ph + hysteresis_ph
        ec_lo = setpoint_ec - hysteresis_ec
        ec_hi = setpoint_ec + hysteresis_ec

        activated = bool(custom_function.is_activated) if hasattr(custom_function, 'is_activated') else False
        state_badge = (
            '<span style="color:#0a0;font-weight:bold;">&#9679; ACTIVE</span>'
            if activated else
            '<span style="color:#a00;font-weight:bold;">&#9679; INACTIVE</span>'
        )

        html = (
            f'{state_badge}'
            f'<br><b>Regulation Bands</b>'
            f'<br>pH: {ph_lo:.2f} &ndash; {ph_hi:.2f} (setpoint {setpoint_ph:.2f})'
            f'<br>EC: {ec_lo:.1f} &ndash; {ec_hi:.1f} (setpoint {setpoint_ec:.1f})'
            f'<br><br><b>Daily Dose Totals (today)</b>'
            f'<br>pH dosed: {daily_ph:.2f} / {max_ph_ml_day:.1f} ml'
            f'<br>EC dosed: {daily_ec:.2f} / {max_ec_ml_day:.1f} ml'
            f'<br><br><b>All-Time Totals</b>'
            f'<br>pH Raise: {total_sec_ph_raise:.2f} sec, {total_ml_ph_raise:.2f} ml'
            f'<br>pH Lower: {total_sec_ph_lower:.2f} sec, {total_ml_ph_lower:.2f} ml'
            f'<br>EC A: {total_sec_ec_a:.2f} sec, {total_ml_ec_a:.2f} ml'
            f'<br>EC B: {total_sec_ec_b:.2f} sec, {total_ml_ec_b:.2f} ml'
            f'<br>EC C: {total_sec_ec_c:.2f} sec, {total_ml_ec_c:.2f} ml'
            f'<br>EC D: {total_sec_ec_d:.2f} sec, {total_ml_ec_d:.2f} ml'
        )
        return {'string_status': html, 'error': []}
    except Exception as err:
        return {'error': [str(err)]}


# ---------------------------------------------------------------------------
# Measurement channels (written to InfluxDB on each dose event)
# Channel 0 = pH dose ml, Channel 1 = EC-A dose ml, Channel 2 = EC-B dose ml
# ---------------------------------------------------------------------------
measurements_dict = {
    0: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'pH Dose'
    },
    1: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'EC-A Dose'
    },
    2: {
        'measurement': 'volume',
        'unit': 'ml',
        'name': 'EC-B Dose'
    }
}


FUNCTION_INFORMATION = {
    'function_name_unique': 'regulate_ph_ec_v2',
    'function_name': 'Regulate pH and EC v2 (Telegram / Safety / Dose Limits)',
    'function_name_short': 'pH/EC v2',
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': False,
    'function_status': function_status_always,

    'message':
        'Enhanced pH/EC regulation with Telegram notifications, water level '
        'safety lock, daily dose limits, InfluxDB dose logging and sensor '
        'sanity checks.'
        '<br><br><b>Outputs</b>: pH Raise (base) and pH Lower (acid) are '
        'optional &mdash; configure only the ones you use. EC supports up to '
        '4 nutrient pumps (A&ndash;D); C and D are optional.'
        '<br><b>Water Level</b>: When a water level sensor is configured, '
        'dosing is blocked whenever the reservoir reads dry.'
        '<br><b>Daily Limits</b>: A configurable per-day maximum prevents '
        'runaway dosing. Limits reset at midnight (server time).'
        '<br><b>Telegram</b>: Receive alerts when pH/EC is in a danger range '
        'or when a measurement cannot be found.'
        '<br><b>Dose Logging</b>: Each dose event writes millilitres to '
        'InfluxDB channels 0 (pH), 1 (EC-A) and 2 (EC-B) for dashboard '
        'graphs.'
        '<br><b>In-Band Halving</b>: When a value is within the regulation '
        'band but on the wrong side of the setpoint, the dose is halved to '
        'approach the target gently.',

    'options_enabled': [
        'custom_options',
        'function_status'
    ],
    'options_disabled': ['measurements_select'],

    # ------------------------------------------------------------------
    # Custom commands
    # ------------------------------------------------------------------
    'custom_commands': [
        {
            'type': 'message',
            'default_value': 'Notification timers can be manually reset before expiration.'
        },
        {
            'id': 'reset_timer_ph',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset pH Alert Timer'
        },
        {
            'id': 'reset_timer_ec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset EC Alert Timer'
        },
        {
            'id': 'reset_timer_no_measure',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Measurement Issue Alert Timer'
        },
        {
            'id': 'reset_timer_all',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset All Alert Timers'
        },
        {
            'type': 'message',
            'default_value': 'Total durations and volumes can be manually reset.'
        },
        {
            'id': 'reset_all_totals',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset All Totals'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'reset_ph_raise_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total Raise pH Duration'
        },
        {
            'id': 'reset_ph_lower_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total Lower pH Duration'
        },
        {
            'id': 'reset_ph_raise_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total Raise pH Volume'
        },
        {
            'id': 'reset_ph_lower_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total Lower pH Volume'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'reset_ec_a_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC A Duration'
        },
        {
            'id': 'reset_ec_a_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC A Volume'
        },
        {
            'id': 'reset_ec_b_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC B Duration'
        },
        {
            'id': 'reset_ec_b_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC B Volume'
        },
        {
            'id': 'reset_ec_c_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC C Duration'
        },
        {
            'id': 'reset_ec_c_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC C Volume'
        },
        {
            'id': 'reset_ec_d_sec',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC D Duration'
        },
        {
            'id': 'reset_ec_d_ml',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Total EC D Volume'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'reset_daily_totals',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Daily Dose Totals'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'send_test_telegram',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Send Test Telegram Message'
        },
    ],

    # ------------------------------------------------------------------
    # Custom options (UI configuration)
    # ------------------------------------------------------------------
    'custom_options': [
        # ---- Timing ----
        {
            'type': 'message',
            'default_value': 'Timing'
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration between measurements or actions')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration to wait before the first operation')
        },
        {
            'id': 'period_status',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'name': 'Status Period (seconds)',
            'phrase': 'The duration (seconds) to update the Function status on the UI'
        },

        # ---- Measurements ----
        {
            'type': 'message',
            'default_value': 'Measurement Options'
        },
        {
            'id': 'select_measurement_ph',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'name': 'pH Measurement',
            'phrase': 'Measurement from the pH input'
        },
        {
            'id': 'measurement_max_age_ph',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext('pH'), lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'select_measurement_ec',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'name': 'EC Measurement',
            'phrase': 'Measurement from the EC input'
        },
        {
            'id': 'measurement_max_age_ec',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext('Electrical Conductivity'), lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'select_measurement_water_level_low',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'name': 'Water Level Low Sensor (optional)',
            'phrase': 'Digital input that reads 1 when water level is LOW (reservoir dry). Leave blank to disable.'
        },
        {
            'id': 'measurement_max_age_water_level',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': 'Water Level Max Age (seconds)',
            'phrase': 'Maximum age of the water level measurement'
        },

        # ---- Outputs ----
        {
            'type': 'message',
            'default_value': 'Output Options'
        },
        {
            'id': 'output_ph_raise',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: pH Dose Raise (Base) [optional]',
            'phrase': 'Select an output to raise the pH (leave blank to disable)'
        },
        {
            'id': 'output_ph_lower',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: pH Dose Lower (Acid) [optional]',
            'phrase': 'Select an output to lower the pH (leave blank to disable)'
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
            'phrase': 'Select the output type for the pH Output Channel'
        },
        {
            'id': 'output_ph_amount',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Output Amount',
            'phrase': 'The amount to send to the pH dosing pumps (duration or volume)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_a',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: EC Dose Nutrient A',
            'phrase': 'Select an output to dose nutrient A'
        },
        {
            'id': 'output_ec_a_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'Nutrient A Output Type',
            'phrase': 'Select the output type for Nutrient A'
        },
        {
            'id': 'output_ec_a_amount',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Nutrient A Output Amount',
            'phrase': 'The amount to send to the Nutrient A dosing pump (duration or volume)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_b',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: EC Dose Nutrient B',
            'phrase': 'Select an output to dose nutrient B'
        },
        {
            'id': 'output_ec_b_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'Nutrient B Output Type',
            'phrase': 'Select the output type for Nutrient B'
        },
        {
            'id': 'output_ec_b_amount',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Nutrient B Output Amount',
            'phrase': 'The amount to send to the Nutrient B dosing pump (duration or volume)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_c',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: EC Dose Nutrient C [optional]',
            'phrase': 'Select an output to dose nutrient C (leave blank to disable)'
        },
        {
            'id': 'output_ec_c_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'Nutrient C Output Type',
            'phrase': 'Select the output type for Nutrient C'
        },
        {
            'id': 'output_ec_c_amount',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Nutrient C Output Amount',
            'phrase': 'The amount to send to the Nutrient C dosing pump (duration or volume)'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'output_ec_d',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels'
            ],
            'name': 'Output: EC Dose Nutrient D [optional]',
            'phrase': 'Select an output to dose nutrient D (leave blank to disable)'
        },
        {
            'id': 'output_ec_d_type',
            'type': 'select',
            'default_value': 'duration_sec',
            'required': True,
            'options_select': [
                ('duration_sec', 'Duration (seconds)'),
                ('volume_ml', 'Volume (ml)')
            ],
            'name': 'Nutrient D Output Type',
            'phrase': 'Select the output type for Nutrient D'
        },
        {
            'id': 'output_ec_d_amount',
            'type': 'float',
            'default_value': 2.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Nutrient D Output Amount',
            'phrase': 'The amount to send to the Nutrient D dosing pump (duration or volume)'
        },

        # ---- Setpoints ----
        {
            'type': 'message',
            'default_value': 'Setpoint Options'
        },
        {
            'id': 'setpoint_ph',
            'type': 'float',
            'default_value': 5.85,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Setpoint',
            'phrase': 'The desired pH setpoint'
        },
        {
            'id': 'hysteresis_ph',
            'type': 'float',
            'default_value': 0.35,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Hysteresis',
            'phrase': 'The hysteresis to determine the pH range'
        },
        {
            'type': 'new_line'
        },
        {
            'id': 'setpoint_ec',
            'type': 'float',
            'default_value': 150.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Setpoint',
            'phrase': 'The desired electrical conductivity setpoint'
        },
        {
            'id': 'hysteresis_ec',
            'type': 'float',
            'default_value': 50.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Hysteresis',
            'phrase': 'The hysteresis to determine the EC range'
        },

        # ---- Danger ranges ----
        {
            'type': 'message',
            'default_value': 'Danger Range Options'
        },
        {
            'id': 'danger_range_ph_high',
            'type': 'float',
            'default_value': 7.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Danger Range (High Value)',
            'phrase': 'The high pH value for the danger range'
        },
        {
            'id': 'danger_range_ph_low',
            'type': 'float',
            'default_value': 5.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Danger Range (Low Value)',
            'phrase': 'The low pH value for the danger range'
        },
        {
            'id': 'danger_ec_too_high',
            'type': 'float',
            'default_value': 3000.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Too High Threshold',
            'phrase': 'EC above this value triggers a danger alert (add water)'
        },

        # ---- Daily dose limits ----
        {
            'type': 'message',
            'default_value': 'Daily Dose Limits'
        },
        {
            'id': 'max_ph_ml_per_day',
            'type': 'float',
            'default_value': 50.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Max pH Dose (ml/day)',
            'phrase': 'Maximum millilitres of pH solution per day (0 = unlimited)'
        },
        {
            'id': 'max_ec_ml_per_day',
            'type': 'float',
            'default_value': 100.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Max EC Dose (ml/day)',
            'phrase': 'Maximum millilitres of EC nutrient per day (0 = unlimited)'
        },
        {
            'id': 'ph_pump_flow_rate',
            'type': 'float',
            'default_value': 1.5,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'pH Pump Flow Rate (ml/min)',
            'phrase': 'Flow rate used to convert duration to ml for daily limit tracking'
        },
        {
            'id': 'ec_pump_flow_rate',
            'type': 'float',
            'default_value': 1.5,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'EC Pump Flow Rate (ml/min)',
            'phrase': 'Flow rate used to convert duration to ml for daily limit tracking'
        },

        # ---- Telegram ----
        {
            'type': 'message',
            'default_value': 'Telegram Notification Options'
        },
        {
            'id': 'telegram_bot_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Telegram Bot Token',
            'phrase': 'Telegram bot token (leave blank to disable notifications)'
        },
        {
            'id': 'telegram_chat_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Telegram Chat ID',
            'phrase': 'Telegram chat ID to send alerts to'
        },
        {
            'id': 'alert_interval_hours',
            'type': 'float',
            'default_value': 12.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Alert Interval (Hours)',
            'phrase': 'Minimum hours between repeated alerts of the same type'
        },
    ]
}


class CustomModule(AbstractFunction):
    """Regulate pH and EC with Telegram, water level safety, daily limits."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()

        self.timer_loop = time.time()

        # ---- Timing ----
        self.period = None
        self.start_offset = None
        self.period_status = None

        # ---- Measurements ----
        self.select_measurement_ph_device_id = None
        self.select_measurement_ph_measurement_id = None
        self.measurement_max_age_ph = None

        self.select_measurement_ec_device_id = None
        self.select_measurement_ec_measurement_id = None
        self.measurement_max_age_ec = None

        self.select_measurement_water_level_low_device_id = None
        self.select_measurement_water_level_low_measurement_id = None
        self.measurement_max_age_water_level = None

        # ---- Outputs ----
        self.output_ph_raise_device_id = None
        self.output_ph_raise_channel_id = None
        self.output_ph_lower_device_id = None
        self.output_ph_lower_channel_id = None
        self.output_ph_type = None
        self.output_ph_amount = None

        self.output_ec_a_device_id = None
        self.output_ec_a_channel_id = None
        self.output_ec_a_type = None
        self.output_ec_a_amount = None

        self.output_ec_b_device_id = None
        self.output_ec_b_channel_id = None
        self.output_ec_b_type = None
        self.output_ec_b_amount = None

        self.output_ec_c_device_id = None
        self.output_ec_c_channel_id = None
        self.output_ec_c_type = None
        self.output_ec_c_amount = None

        self.output_ec_d_device_id = None
        self.output_ec_d_channel_id = None
        self.output_ec_d_type = None
        self.output_ec_d_amount = None

        # ---- Setpoints / danger ----
        self.setpoint_ph = None
        self.hysteresis_ph = None
        self.setpoint_ec = None
        self.hysteresis_ec = None
        self.danger_range_ph_high = None
        self.danger_range_ph_low = None
        self.danger_ec_too_high = None

        # ---- Daily limits ----
        self.max_ph_ml_per_day = None
        self.max_ec_ml_per_day = None
        self.ph_pump_flow_rate = None
        self.ec_pump_flow_rate = None

        # ---- Telegram ----
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self.alert_interval_hours = None

        # ---- Runtime state ----
        self.range_ph = (0, 14)
        self.range_ec = (0, 10000)

        self.output_ph_raise_channel = None
        self.output_ph_lower_channel = None
        self.output_ec_a_channel = None
        self.output_ec_b_channel = None
        self.output_ec_c_channel = None
        self.output_ec_d_channel = None

        self.output_units = {
            '': 'sec',
            'duration_sec': 'sec',
            'volume_ml': 'ml'
        }

        self.ph_type = None
        self.ec_a_type = None
        self.ec_b_type = None
        self.ec_c_type = None
        self.ec_d_type = None

        self.list_doses = []
        self.ratio_letters = []
        self.ratio_numbers = []

        self.alert_timers = {
            'notify_ph': 0,
            'notify_ec': 0,
            'notify_none': 0,
            'notify_water_level': 0,
            'notify_daily_limit': 0,
        }

        self.water_level_locked = False

        # Persistent totals (restored from DB)
        self.total = {
            'sec_ph_raise': self.get_custom_option('sec_ph_raise'),
            'sec_ph_lower': self.get_custom_option('sec_ph_lower'),
            'sec_ec_a': self.get_custom_option('sec_ec_a'),
            'sec_ec_b': self.get_custom_option('sec_ec_b'),
            'sec_ec_c': self.get_custom_option('sec_ec_c'),
            'sec_ec_d': self.get_custom_option('sec_ec_d'),
            'ml_ph_raise': self.get_custom_option('ml_ph_raise'),
            'ml_ph_lower': self.get_custom_option('ml_ph_lower'),
            'ml_ec_a': self.get_custom_option('ml_ec_a'),
            'ml_ec_b': self.get_custom_option('ml_ec_b'),
            'ml_ec_c': self.get_custom_option('ml_ec_c'),
            'ml_ec_d': self.get_custom_option('ml_ec_d'),
        }

        # Daily dose tracking (JSON-persisted)
        self.daily_dosed = {}  # {date_str: {'ph_ml': float, 'ec_ml': float}}

        if self.total['sec_ph_raise'] is None:
            self.reset_all_totals({})

        # Set custom options
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

        self.range_ph = (
            self.setpoint_ph - self.hysteresis_ph,
            self.setpoint_ph + self.hysteresis_ph
        )
        self.range_ec = (
            self.setpoint_ec - self.hysteresis_ec,
            self.setpoint_ec + self.hysteresis_ec
        )

        # Resolve output channels
        self.output_ph_raise_channel = self.get_output_channel_from_channel_id(
            self.output_ph_raise_channel_id)
        self.output_ph_lower_channel = self.get_output_channel_from_channel_id(
            self.output_ph_lower_channel_id)
        self.output_ec_a_channel = self.get_output_channel_from_channel_id(
            self.output_ec_a_channel_id)
        self.output_ec_b_channel = self.get_output_channel_from_channel_id(
            self.output_ec_b_channel_id)
        self.output_ec_c_channel = self.get_output_channel_from_channel_id(
            self.output_ec_c_channel_id)
        self.output_ec_d_channel = self.get_output_channel_from_channel_id(
            self.output_ec_d_channel_id)

        # Ensure any None totals become 0
        for key in list(self.total):
            if self.total[key] is None:
                self.total[key] = self.set_custom_option(key, 0)

        self.ph_type = 'vol' if self.output_ph_type == 'volume_ml' else 'sec'
        self.ec_a_type = 'vol' if self.output_ec_a_type == 'volume_ml' else 'sec'
        self.ec_b_type = 'vol' if self.output_ec_b_type == 'volume_ml' else 'sec'
        self.ec_c_type = 'vol' if self.output_ec_c_type == 'volume_ml' else 'sec'
        self.ec_d_type = 'vol' if self.output_ec_d_type == 'volume_ml' else 'sec'

        # Build nutrient ratio info
        for label, dev_id, amount, out_type in [
            ('A', self.output_ec_a_device_id, self.output_ec_a_amount, self.output_ec_a_type),
            ('B', self.output_ec_b_device_id, self.output_ec_b_amount, self.output_ec_b_type),
            ('C', self.output_ec_c_device_id, self.output_ec_c_amount, self.output_ec_c_type),
            ('D', self.output_ec_d_device_id, self.output_ec_d_amount, self.output_ec_d_type),
        ]:
            if dev_id:
                self.ratio_letters.append(label)
                self.ratio_numbers.append(str(amount))
                self.list_doses.append(
                    f"{amount} {self.output_units.get(out_type, 'sec')} Nut {label}")

        # Load daily dose state
        self._load_daily_dosed()

        self.logger.info(
            f"pH/EC v2 initialized. pH band: {self.range_ph[0]:.2f}-{self.range_ph[1]:.2f}, "
            f"EC band: {self.range_ec[0]:.1f}-{self.range_ec[1]:.1f}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def loop(self):
        if self.timer_loop > time.time():
            return

        while self.timer_loop < time.time():
            self.timer_loop += self.period

        self._reset_daily_if_needed()

        # --- Water level safety check ---
        if self._check_water_level_lock():
            self.logger.warning("Dosing blocked: water level sensor indicates reservoir is dry")
            return

        message = ""
        enabled_ph = False
        enabled_ec = False
        malfunction_ph = False
        malfunction_ec = False
        last_measurement_ph = None
        last_measurement_ec = None

        # --- Read pH ---
        if self.select_measurement_ph_device_id and self.select_measurement_ph_measurement_id:
            enabled_ph = True
            last_measurement_ph = self._read(
                self.select_measurement_ph_device_id,
                self.select_measurement_ph_measurement_id,
                self.measurement_max_age_ph,
                'pH')
            if last_measurement_ph is None:
                malfunction_ph = True
            elif not self._sanity_ph(last_measurement_ph[1]):
                self.logger.error(
                    f"pH sanity check failed: {last_measurement_ph[1]:.2f} "
                    f"(must be 3-10). Skipping regulation.")
                malfunction_ph = True

        # --- Read EC ---
        if self.select_measurement_ec_device_id and self.select_measurement_ec_measurement_id:
            enabled_ec = True
            last_measurement_ec = self._read(
                self.select_measurement_ec_device_id,
                self.select_measurement_ec_measurement_id,
                self.measurement_max_age_ec,
                'EC')
            if last_measurement_ec is None:
                malfunction_ec = True
            elif not self._sanity_ec(last_measurement_ec[1]):
                self.logger.error(
                    f"EC sanity check failed: {last_measurement_ec[1]:.2f} "
                    f"(must be 0-10000). Skipping regulation.")
                malfunction_ec = True

        # --- Alert on missing measurement ---
        if enabled_ph or enabled_ec:
            if malfunction_ph:
                message += "\nWarning: No valid pH measurement!"
            if malfunction_ec:
                message += "\nWarning: No valid EC measurement!"
            if message:
                self._tg_send_throttled('notify_none', message.strip())

        regulate_ph = enabled_ph and not malfunction_ph
        regulate_ec = enabled_ec and not malfunction_ec

        # ==============================================================
        # 1. pH danger check (takes priority over everything)
        # ==============================================================

        # pH dangerously low -> add base (raise)
        if regulate_ph and last_measurement_ph[1] < self.danger_range_ph_low:
            msg = (
                f"DANGER: pH is critically low: {last_measurement_ph[1]:.2f} "
                f"(< {self.danger_range_ph_low:.2f}). "
                f"Dispensing {self.output_ph_amount} "
                f"{self.output_units.get(self.output_ph_type, 'sec')} base.")
            self.logger.warning(msg)
            self._dose_ph_raise(self.output_ph_amount)
            self._tg_send_throttled('notify_ph', msg)
            return

        # pH dangerously high -> add acid (lower)
        if regulate_ph and last_measurement_ph[1] > self.danger_range_ph_high:
            msg = (
                f"DANGER: pH is critically high: {last_measurement_ph[1]:.2f} "
                f"(> {self.danger_range_ph_high:.2f}). "
                f"Dispensing {self.output_ph_amount} "
                f"{self.output_units.get(self.output_ph_type, 'sec')} acid.")
            self.logger.warning(msg)
            self._dose_ph_lower(self.output_ph_amount)
            self._tg_send_throttled('notify_ph', msg)
            return

        # ==============================================================
        # 2. EC regulation (only if pH is not in danger)
        # ==============================================================

        if regulate_ec:
            ec_val = last_measurement_ec[1]

            # EC too high -> alert (cannot dilute automatically)
            if ec_val > self.range_ec[1]:
                if ec_val > self.danger_ec_too_high:
                    msg = (
                        f"DANGER: EC is extremely high: {ec_val:.1f} "
                        f"(> {self.danger_ec_too_high:.1f}). Add water to dilute!")
                else:
                    msg = (
                        f"EC is above range: {ec_val:.1f} "
                        f"(> {self.range_ec[1]:.1f}). Add water to dilute.")
                self.logger.warning(msg)
                self._tg_send_throttled('notify_ec', msg)

            # EC too low -> dose nutrients
            elif ec_val < self.range_ec[0]:
                self.logger.debug(
                    f"EC: {ec_val:.1f} < {self.range_ec[0]:.1f}. "
                    f"Dosing {':'.join(self.ratio_numbers)} "
                    f"({':'.join(self.ratio_letters)})")
                self._dose_ec(half=False)

            # EC in band but below setpoint -> half dose
            elif ec_val < self.setpoint_ec:
                self.logger.debug(
                    f"EC in-band but below setpoint: {ec_val:.1f} "
                    f"< {self.setpoint_ec:.1f}. Halved dose.")
                self._dose_ec(half=True)

        # ==============================================================
        # 3. pH regulation (only when EC is not critically out of range)
        # ==============================================================

        if regulate_ph:
            ph_val = last_measurement_ph[1]

            # pH below lower band -> add base
            if ph_val < self.range_ph[0]:
                amount = self.output_ph_amount
                self.logger.debug(
                    f"pH {ph_val:.2f} < {self.range_ph[0]:.2f}. "
                    f"Dispensing {amount} "
                    f"{self.output_units.get(self.output_ph_type, 'sec')} base.")
                self._dose_ph_raise(amount)

            # pH above upper band -> add acid
            elif ph_val > self.range_ph[1]:
                amount = self.output_ph_amount
                self.logger.debug(
                    f"pH {ph_val:.2f} > {self.range_ph[1]:.2f}. "
                    f"Dispensing {amount} "
                    f"{self.output_units.get(self.output_ph_type, 'sec')} acid.")
                self._dose_ph_lower(amount)

            # pH in band but above setpoint -> half dose acid
            elif ph_val > self.setpoint_ph:
                amount = self.output_ph_amount / 2.0
                self.logger.debug(
                    f"pH in-band but above setpoint: {ph_val:.2f} "
                    f"> {self.setpoint_ph:.2f}. Halved acid dose: {amount:.2f}")
                self._dose_ph_lower(amount)

            # pH in band but below setpoint -> half dose base
            elif ph_val < self.setpoint_ph:
                amount = self.output_ph_amount / 2.0
                self.logger.debug(
                    f"pH in-band but below setpoint: {ph_val:.2f} "
                    f"< {self.setpoint_ph:.2f}. Halved base dose: {amount:.2f}")
                self._dose_ph_raise(amount)

    # ------------------------------------------------------------------
    # Dosing helpers
    # ------------------------------------------------------------------

    def _dose_ph_raise(self, amount):
        """Dose base solution to raise pH."""
        if not self.output_ph_raise_device_id:
            self.logger.debug("pH Raise output not configured, skipping")
            return

        ml = self._amount_to_ml(amount, self.output_ph_type, self.ph_pump_flow_rate)
        if not self._daily_limit_ok('ph', ml):
            self.logger.warning(
                f"Daily pH limit reached ({self.max_ph_ml_per_day} ml). Skipping dose.")
            self._tg_send_throttled(
                'notify_daily_limit',
                f"Daily pH dose limit reached ({self.max_ph_ml_per_day} ml/day). Dosing paused.")
            return

        self._track_total('ph_raise', amount)
        self._track_daily('ph', ml)

        output_on_off = threading.Thread(
            target=self.control.output_on_off,
            args=(self.output_ph_raise_device_id, 'on',),
            kwargs={
                'output_type': self.ph_type,
                'amount': amount,
                'output_channel': self.output_ph_raise_channel
            })
        output_on_off.start()

        self._log_dose(0, ml)

    def _dose_ph_lower(self, amount):
        """Dose acid solution to lower pH."""
        if not self.output_ph_lower_device_id:
            self.logger.debug("pH Lower output not configured, skipping")
            return

        ml = self._amount_to_ml(amount, self.output_ph_type, self.ph_pump_flow_rate)
        if not self._daily_limit_ok('ph', ml):
            self.logger.warning(
                f"Daily pH limit reached ({self.max_ph_ml_per_day} ml). Skipping dose.")
            self._tg_send_throttled(
                'notify_daily_limit',
                f"Daily pH dose limit reached ({self.max_ph_ml_per_day} ml/day). Dosing paused.")
            return

        self._track_total('ph_lower', amount)
        self._track_daily('ph', ml)

        output_on_off = threading.Thread(
            target=self.control.output_on_off,
            args=(self.output_ph_lower_device_id, 'on',),
            kwargs={
                'output_type': self.ph_type,
                'amount': amount,
                'output_channel': self.output_ph_lower_channel
            })
        output_on_off.start()

        self._log_dose(0, ml)

    def _dose_ec(self, half=False):
        """Dose all configured EC nutrient pumps. If half=True, amounts are halved."""
        pumps = [
            ('A', self.output_ec_a_device_id, self.output_ec_a_channel,
             self.ec_a_type, self.output_ec_a_type, self.output_ec_a_amount, 'ec_a'),
            ('B', self.output_ec_b_device_id, self.output_ec_b_channel,
             self.ec_b_type, self.output_ec_b_type, self.output_ec_b_amount, 'ec_b'),
            ('C', self.output_ec_c_device_id, self.output_ec_c_channel,
             self.ec_c_type, self.output_ec_c_type, self.output_ec_c_amount, 'ec_c'),
            ('D', self.output_ec_d_device_id, self.output_ec_d_channel,
             self.ec_d_type, self.output_ec_d_type, self.output_ec_d_amount, 'ec_d'),
        ]

        total_ml_this_dose = 0.0
        for label, dev_id, channel, out_type_short, out_type_key, base_amount, total_key in pumps:
            if not dev_id:
                continue
            amount = base_amount / 2.0 if half else base_amount
            ml = self._amount_to_ml(amount, out_type_key, self.ec_pump_flow_rate)
            total_ml_this_dose += ml

        if not self._daily_limit_ok('ec', total_ml_this_dose):
            self.logger.warning(
                f"Daily EC limit reached ({self.max_ec_ml_per_day} ml). Skipping dose.")
            self._tg_send_throttled(
                'notify_daily_limit',
                f"Daily EC dose limit reached ({self.max_ec_ml_per_day} ml/day). Dosing paused.")
            return

        for idx, (label, dev_id, channel, out_type_short, out_type_key, base_amount, total_key) in enumerate(pumps):
            if not dev_id:
                continue
            amount = base_amount / 2.0 if half else base_amount
            ml = self._amount_to_ml(amount, out_type_key, self.ec_pump_flow_rate)

            self._track_total(total_key, amount)
            self._track_daily('ec', ml)

            output_on_off = threading.Thread(
                target=self.control.output_on_off,
                args=(dev_id, 'on',),
                kwargs={
                    'output_type': out_type_short,
                    'amount': amount,
                    'output_channel': channel
                })
            output_on_off.start()

            # Log to InfluxDB: channel 1 = EC-A, channel 2 = EC-B
            # (C and D are tracked in totals but only A/B have dedicated InfluxDB channels)
            if label == 'A':
                self._log_dose(1, ml)
            elif label == 'B':
                self._log_dose(2, ml)

    # ------------------------------------------------------------------
    # Measurement helpers
    # ------------------------------------------------------------------

    def _read(self, device_id, measurement_id, max_age, label):
        """Read the last measurement. Returns (timestamp, value) or None."""
        last = self.get_last_measurement(device_id, measurement_id, max_age=max_age)
        if last:
            self.logger.debug(f"Last {label}: ts={last[0]}, val={last[1]}")
            return last
        self.logger.error(
            f"No {label} measurement found (device={device_id}, "
            f"measurement={measurement_id}, max_age={max_age}s)")
        return None

    @staticmethod
    def _sanity_ph(value):
        """Return True if the pH value is plausible."""
        return 3.0 <= value <= 10.0

    @staticmethod
    def _sanity_ec(value):
        """Return True if the EC value is plausible."""
        return 0.0 <= value <= 10000.0

    # ------------------------------------------------------------------
    # Water level safety
    # ------------------------------------------------------------------

    def _check_water_level_lock(self):
        """Return True if dosing should be blocked due to low water level."""
        if (not self.select_measurement_water_level_low_device_id or
                not self.select_measurement_water_level_low_measurement_id):
            self.water_level_locked = False
            return False

        last = self.get_last_measurement(
            self.select_measurement_water_level_low_device_id,
            self.select_measurement_water_level_low_measurement_id,
            max_age=self.measurement_max_age_water_level)

        if last is None:
            # No measurement available — assume safe (do not block)
            self.logger.debug("Water level sensor: no measurement, assuming safe")
            self.water_level_locked = False
            return False

        # Convention: sensor value == 1 means water is LOW (dry)
        is_dry = bool(last[1])
        if is_dry and not self.water_level_locked:
            self.water_level_locked = True
            self._tg_send_throttled(
                'notify_water_level',
                "Water level LOW — all dosing blocked until reservoir is refilled!")
        elif not is_dry:
            self.water_level_locked = False

        return is_dry

    # ------------------------------------------------------------------
    # Daily dose tracking
    # ------------------------------------------------------------------

    def _reset_daily_if_needed(self):
        """Reset daily counters if the date has changed."""
        today = datetime.date.today().isoformat()
        if today not in self.daily_dosed:
            # Prune old dates (keep last 7 days for reference)
            cutoff = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
            self.daily_dosed = {
                k: v for k, v in self.daily_dosed.items() if k >= cutoff
            }
            self.daily_dosed[today] = {'ph_ml': 0.0, 'ec_ml': 0.0}
            self._save_daily_dosed()

    def _load_daily_dosed(self):
        """Load daily dose tracking from persistent storage."""
        raw = self.get_custom_option('daily_dosed_json', default_return='{}')
        try:
            self.daily_dosed = json.loads(raw) if isinstance(raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            self.daily_dosed = {}
        today = datetime.date.today().isoformat()
        if today not in self.daily_dosed:
            self.daily_dosed[today] = {'ph_ml': 0.0, 'ec_ml': 0.0}

    def _save_daily_dosed(self):
        """Persist daily dose tracking to DB."""
        self.set_custom_option('daily_dosed_json', json.dumps(self.daily_dosed))

    def _track_daily(self, category, ml):
        """Add ml to today's daily total for 'ph' or 'ec'."""
        today = datetime.date.today().isoformat()
        if today not in self.daily_dosed:
            self.daily_dosed[today] = {'ph_ml': 0.0, 'ec_ml': 0.0}
        key = f'{category}_ml'
        self.daily_dosed[today][key] = self.daily_dosed[today].get(key, 0.0) + ml
        self._save_daily_dosed()

    def _daily_limit_ok(self, category, ml_to_add):
        """Check whether adding ml_to_add would exceed the daily limit.

        Returns True if dosing is permitted.
        """
        if category == 'ph':
            limit = self.max_ph_ml_per_day
        else:
            limit = self.max_ec_ml_per_day

        if not limit or limit <= 0:
            return True  # 0 = unlimited

        today = datetime.date.today().isoformat()
        current = self.daily_dosed.get(today, {}).get(f'{category}_ml', 0.0)
        return (current + ml_to_add) <= limit

    def _amount_to_ml(self, amount, output_type, flow_rate_ml_min):
        """Convert an output amount to millilitres.

        If the output type is volume_ml the amount *is* ml.
        If it is duration_sec we use the configured flow rate.
        """
        if output_type == 'volume_ml':
            return amount
        # duration_sec: ml = (seconds / 60) * flow_rate_ml_min
        return (amount / 60.0) * flow_rate_ml_min

    # ------------------------------------------------------------------
    # Total tracking (all-time, persisted per option key)
    # ------------------------------------------------------------------

    def _track_total(self, pump_key, amount):
        """Increment the all-time total for a pump.

        pump_key examples: 'ph_raise', 'ph_lower', 'ec_a', 'ec_b', etc.
        """
        # Determine sec vs ml
        type_map = {
            'ph_raise': self.output_ph_type,
            'ph_lower': self.output_ph_type,
            'ec_a': self.output_ec_a_type,
            'ec_b': self.output_ec_b_type,
            'ec_c': self.output_ec_c_type,
            'ec_d': self.output_ec_d_type,
        }
        out_type = type_map.get(pump_key, 'duration_sec')
        prefix = 'ml' if out_type == 'volume_ml' else 'sec'
        db_key = f'{prefix}_{pump_key}'

        current = self.get_custom_option(db_key, default_return=0) or 0
        new_val = current + amount
        self.set_custom_option(db_key, new_val)
        self.total[db_key] = new_val

    # ------------------------------------------------------------------
    # InfluxDB dose logging
    # ------------------------------------------------------------------

    def _log_dose(self, channel, ml):
        """Write a dose event to InfluxDB for dashboard graphing.

        channel 0 = pH dose, 1 = EC-A dose, 2 = EC-B dose
        """
        if ml <= 0:
            return
        try:
            write_db = threading.Thread(
                target=write_influxdb_value,
                args=(self.unique_id, 'ml', ml),
                kwargs={'measure': 'volume', 'channel': channel})
            write_db.start()
        except Exception as err:
            self.logger.error(f"InfluxDB write error (ch{channel}): {err}")

    # ------------------------------------------------------------------
    # Telegram notification helpers
    # ------------------------------------------------------------------

    def _tg_send_throttled(self, timer_key, message):
        """Send a Telegram message if the throttle timer has expired."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return
        now = time.time()
        if self.alert_timers.get(timer_key, 0) < now:
            interval_sec = (self.alert_interval_hours or 12) * 3600
            self.alert_timers[timer_key] = now + interval_sec
            self._tg_send(message)

    def _tg_send(self, message):
        """Send a Telegram message (fire-and-forget in thread)."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return
        t = threading.Thread(target=self._tg_post, args=(message,))
        t.daemon = True
        t.start()

    def _tg_post(self, message):
        """Perform the actual HTTP POST to Telegram API."""
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                self.logger.error(
                    f"Telegram send failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as err:
            self.logger.error(f"Telegram send error: {err}")

    # ------------------------------------------------------------------
    # Persistent storage helper
    # ------------------------------------------------------------------

    def _load(self, key, default=0):
        """Load a custom option with a safe default."""
        val = self.get_custom_option(key, default_return=default)
        if val is None:
            return default
        return val

    # ------------------------------------------------------------------
    # Custom command handlers
    # ------------------------------------------------------------------

    def reset_timer_ph(self, args_dict):
        self.alert_timers['notify_ph'] = 0
        return "Success: pH alert timer reset"

    def reset_timer_ec(self, args_dict):
        self.alert_timers['notify_ec'] = 0
        return "Success: EC alert timer reset"

    def reset_timer_no_measure(self, args_dict):
        self.alert_timers['notify_none'] = 0
        return "Success: Measurement issue alert timer reset"

    def reset_timer_all(self, args_dict):
        for key in self.alert_timers:
            self.alert_timers[key] = 0
        return "Success: All alert timers reset"

    def reset_all_totals(self, args_dict):
        self.total = {
            'sec_ph_raise': self.set_custom_option('sec_ph_raise', 0),
            'sec_ph_lower': self.set_custom_option('sec_ph_lower', 0),
            'sec_ec_a': self.set_custom_option('sec_ec_a', 0),
            'sec_ec_b': self.set_custom_option('sec_ec_b', 0),
            'sec_ec_c': self.set_custom_option('sec_ec_c', 0),
            'sec_ec_d': self.set_custom_option('sec_ec_d', 0),
            'ml_ph_raise': self.set_custom_option('ml_ph_raise', 0),
            'ml_ph_lower': self.set_custom_option('ml_ph_lower', 0),
            'ml_ec_a': self.set_custom_option('ml_ec_a', 0),
            'ml_ec_b': self.set_custom_option('ml_ec_b', 0),
            'ml_ec_c': self.set_custom_option('ml_ec_c', 0),
            'ml_ec_d': self.set_custom_option('ml_ec_d', 0),
        }
        return "Success: All totals reset to 0"

    def reset_daily_totals(self, args_dict):
        today = datetime.date.today().isoformat()
        self.daily_dosed[today] = {'ph_ml': 0.0, 'ec_ml': 0.0}
        self._save_daily_dosed()
        return "Success: Daily dose totals reset"

    def reset_ph_raise_sec(self, args_dict):
        self.total['sec_ph_raise'] = self.set_custom_option('sec_ph_raise', 0)
        return "Success"

    def reset_ph_lower_sec(self, args_dict):
        self.total['sec_ph_lower'] = self.set_custom_option('sec_ph_lower', 0)
        return "Success"

    def reset_ph_raise_ml(self, args_dict):
        self.total['ml_ph_raise'] = self.set_custom_option('ml_ph_raise', 0)
        return "Success"

    def reset_ph_lower_ml(self, args_dict):
        self.total['ml_ph_lower'] = self.set_custom_option('ml_ph_lower', 0)
        return "Success"

    def reset_ec_a_sec(self, args_dict):
        self.total['sec_ec_a'] = self.set_custom_option('sec_ec_a', 0)
        return "Success"

    def reset_ec_a_ml(self, args_dict):
        self.total['ml_ec_a'] = self.set_custom_option('ml_ec_a', 0)
        return "Success"

    def reset_ec_b_sec(self, args_dict):
        self.total['sec_ec_b'] = self.set_custom_option('sec_ec_b', 0)
        return "Success"

    def reset_ec_b_ml(self, args_dict):
        self.total['ml_ec_b'] = self.set_custom_option('ml_ec_b', 0)
        return "Success"

    def reset_ec_c_sec(self, args_dict):
        self.total['sec_ec_c'] = self.set_custom_option('sec_ec_c', 0)
        return "Success"

    def reset_ec_c_ml(self, args_dict):
        self.total['ml_ec_c'] = self.set_custom_option('ml_ec_c', 0)
        return "Success"

    def reset_ec_d_sec(self, args_dict):
        self.total['sec_ec_d'] = self.set_custom_option('sec_ec_d', 0)
        return "Success"

    def reset_ec_d_ml(self, args_dict):
        self.total['ml_ec_d'] = self.set_custom_option('ml_ec_d', 0)
        return "Success"

    def send_test_telegram(self, args_dict):
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return "Error: Telegram bot token or chat ID not configured"
        self._tg_send(
            "Test message from Mycodo pH/EC v2 regulator. "
            "If you see this, notifications are working!")
        return "Success: Test message sent"

    # ------------------------------------------------------------------
    # Status panel (instance method — used when function IS active)
    # ------------------------------------------------------------------

    def function_status(self):
        """Return HTML status for the Function Status widget."""
        now = time.time()

        # Countdown to next loop
        remaining = max(0, self.timer_loop - now)
        mins, secs = divmod(int(remaining), 60)
        countdown_str = f"{mins}m {secs}s"

        # Nutrient ratio display
        str_ratio = "(no EC dosing enabled)"
        if self.ratio_numbers and self.ratio_letters:
            str_ratio = f"at {':'.join(self.ratio_numbers)} ({':'.join(self.ratio_letters)})"

        # Daily stats
        today = datetime.date.today().isoformat()
        day_data = self.daily_dosed.get(today, {'ph_ml': 0, 'ec_ml': 0})
        daily_ph = day_data.get('ph_ml', 0)
        daily_ec = day_data.get('ec_ml', 0)

        # Water level badge
        if self.water_level_locked:
            wl_badge = '<span style="color:#d00;font-weight:bold;">LOCKED (dry)</span>'
        elif (self.select_measurement_water_level_low_device_id and
              self.select_measurement_water_level_low_measurement_id):
            wl_badge = '<span style="color:#0a0;">OK</span>'
        else:
            wl_badge = '<span style="color:#888;">not configured</span>'

        # Telegram badge
        if self.telegram_bot_token and self.telegram_chat_id:
            tg_badge = '<span style="color:#0a0;">enabled</span>'
        else:
            tg_badge = '<span style="color:#888;">disabled</span>'

        # Build status HTML
        html = (
            f'<b>Next check in:</b> {countdown_str}'
            f'<br><br><b>Regulation Bands</b>'
            f'<br>pH: {self.range_ph[0]:.2f} &ndash; {self.range_ph[1]:.2f}'
            f' (setpoint {self.setpoint_ph:.2f})'
            f'<br>pH dose: {self.output_ph_amount:.2f} '
            f'{self.output_units.get(self.output_ph_type, "sec")}'
            f'<br>EC: {self.range_ec[0]:.1f} &ndash; {self.range_ec[1]:.1f}'
            f' (setpoint {self.setpoint_ec:.1f}) {str_ratio}'
        )

        # Per-pump amounts
        for label, dev_id, amount, out_type in [
            ('A', self.output_ec_a_device_id, self.output_ec_a_amount, self.output_ec_a_type),
            ('B', self.output_ec_b_device_id, self.output_ec_b_amount, self.output_ec_b_type),
            ('C', self.output_ec_c_device_id, self.output_ec_c_amount, self.output_ec_c_type),
            ('D', self.output_ec_d_device_id, self.output_ec_d_amount, self.output_ec_d_type),
        ]:
            if dev_id:
                html += (
                    f'<br>EC Nut {label}: {amount:.2f} '
                    f'{self.output_units.get(out_type, "sec")}')

        html += (
            f'<br><br><b>Daily Dose Totals (today)</b>'
            f'<br>pH: {daily_ph:.2f} / '
            f'{self.max_ph_ml_per_day:.1f} ml'
            f'<br>EC: {daily_ec:.2f} / '
            f'{self.max_ec_ml_per_day:.1f} ml'
        )

        html += (
            f'<br><br><b>All-Time Totals</b>'
            f'<br>pH Raise: {self.total.get("sec_ph_raise", 0):.2f} sec, '
            f'{self.total.get("ml_ph_raise", 0):.2f} ml'
            f'<br>pH Lower: {self.total.get("sec_ph_lower", 0):.2f} sec, '
            f'{self.total.get("ml_ph_lower", 0):.2f} ml'
            f'<br>EC A: {self.total.get("sec_ec_a", 0):.2f} sec, '
            f'{self.total.get("ml_ec_a", 0):.2f} ml'
            f'<br>EC B: {self.total.get("sec_ec_b", 0):.2f} sec, '
            f'{self.total.get("ml_ec_b", 0):.2f} ml'
            f'<br>EC C: {self.total.get("sec_ec_c", 0):.2f} sec, '
            f'{self.total.get("ml_ec_c", 0):.2f} ml'
            f'<br>EC D: {self.total.get("sec_ec_d", 0):.2f} sec, '
            f'{self.total.get("ml_ec_d", 0):.2f} ml'
        )

        html += (
            f'<br><br><b>Safety</b>'
            f'<br>Water level: {wl_badge}'
            f'<br>Telegram: {tg_badge}'
        )

        return {
            'string_status': html,
            'error': []
        }

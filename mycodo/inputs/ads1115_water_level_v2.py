# coding=utf-8
#
# ADS1115 Water Level Input
# Specialized ADS1115 input for analog water level/pressure sensors
# (e.g. QDY30A). Reads voltage per channel and converts to water level
# (cm) using 2-point calibration. Volume (L) is derived from container
# dimensions and logged.
#
import copy

from mycodo.inputs.base_input import AbstractInput

# 4 channels matching ADC CH0-CH3, each outputs water level in cm
measurements_dict = {
    0: {'measurement': 'length', 'unit': 'cm'},
    1: {'measurement': 'length', 'unit': 'cm'},
    2: {'measurement': 'length', 'unit': 'cm'},
    3: {'measurement': 'length', 'unit': 'cm'},
}

INPUT_INFORMATION = {
    'input_name_unique': 'ADS1115_WATER_LEVEL',
    'input_manufacturer': 'Texas Instruments',
    'input_name': 'ADS1115: Water Level',
    'input_name_short': 'ADS1115 Water Level',
    'input_library': 'Adafruit_CircuitPython_ADS1x15',
    'measurements_name': 'Water Level',
    'measurements_dict': measurements_dict,

    'message': 'Reads analog water level/pressure sensors (e.g. QDY30A) via '
               'ADS1115 ADC. Each channel (CH0-CH3) can connect to an independent '
               'sensor in a different tank. Enable the channels you use under '
               '"Measurements Enabled". Set calibration and container dimensions '
               'per channel under "Custom Options". Use the buttons under '
               '"Commands" for quick 2-point calibration. '
               'Volume (L) is logged per reading; for dashboard graphs of volume, '
               'create a Math Function: Level x (Tank Volume / Tank Height).',

    'options_enabled': [
        'measurements_select',
        'i2c_location',
        'adc_gain',
        'period',
        'pre_output'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'usb.core', 'pyusb==1.1.1'),
        ('pip-pypi', 'adafruit_extended_bus', 'Adafruit-extended-bus==1.0.2'),
        ('pip-pypi', 'adafruit_ads1x15', 'adafruit-circuitpython-ads1x15==2.2.25')
    ],
    'interfaces': ['I2C'],
    'i2c_location': ['0x48', '0x49', '0x4A', '0x4B'],
    'i2c_address_editable': False,

    'adc_gain': [(0, '2/3 (±6.144 V)'),
                 (1, '1 (±4.096 V)'),
                 (2, '2 (±2.048 V)'),
                 (4, '4 (±1.024 V)'),
                 (8, '8 (±0.512 V)'),
                 (16, '16 (±0.256 V)')],

    'custom_options': [
        # --- CH0 ---
        {
            'type': 'message',
            'default_value': '<strong>CH0 Calibration & Tank</strong>'
        },
        {
            'id': 'cal_v1_0',
            'type': 'float',
            'default_value': 0.073,
            'name': 'CH0 V Low',
            'phrase': 'Voltage at low water level'
        },
        {
            'id': 'cal_l1_0',
            'type': 'float',
            'default_value': 0.0,
            'name': 'CH0 Level Low (cm)',
            'phrase': 'Known water level at low point'
        },
        {
            'id': 'cal_v2_0',
            'type': 'float',
            'default_value': 1.216,
            'name': 'CH0 V High',
            'phrase': 'Voltage at high water level'
        },
        {
            'id': 'cal_l2_0',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH0 Level High (cm)',
            'phrase': 'Known water level at high point'
        },
        {
            'id': 'height_0',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH0 Tank Height (cm)',
            'phrase': 'Container height at full capacity'
        },
        {
            'id': 'vol_0',
            'type': 'float',
            'default_value': 50.0,
            'name': 'CH0 Tank Volume (L)',
            'phrase': 'Container volume at full capacity'
        },
        {'type': 'new_line'},

        # --- CH1 ---
        {
            'type': 'message',
            'default_value': '<strong>CH1 Calibration & Tank</strong>'
        },
        {
            'id': 'cal_v1_1',
            'type': 'float',
            'default_value': 0.073,
            'name': 'CH1 V Low',
            'phrase': 'Voltage at low water level'
        },
        {
            'id': 'cal_l1_1',
            'type': 'float',
            'default_value': 0.0,
            'name': 'CH1 Level Low (cm)',
            'phrase': 'Known water level at low point'
        },
        {
            'id': 'cal_v2_1',
            'type': 'float',
            'default_value': 1.216,
            'name': 'CH1 V High',
            'phrase': 'Voltage at high water level'
        },
        {
            'id': 'cal_l2_1',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH1 Level High (cm)',
            'phrase': 'Known water level at high point'
        },
        {
            'id': 'height_1',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH1 Tank Height (cm)',
            'phrase': 'Container height at full capacity'
        },
        {
            'id': 'vol_1',
            'type': 'float',
            'default_value': 50.0,
            'name': 'CH1 Tank Volume (L)',
            'phrase': 'Container volume at full capacity'
        },
        {'type': 'new_line'},

        # --- CH2 ---
        {
            'type': 'message',
            'default_value': '<strong>CH2 Calibration & Tank</strong>'
        },
        {
            'id': 'cal_v1_2',
            'type': 'float',
            'default_value': 0.073,
            'name': 'CH2 V Low',
            'phrase': 'Voltage at low water level'
        },
        {
            'id': 'cal_l1_2',
            'type': 'float',
            'default_value': 0.0,
            'name': 'CH2 Level Low (cm)',
            'phrase': 'Known water level at low point'
        },
        {
            'id': 'cal_v2_2',
            'type': 'float',
            'default_value': 1.216,
            'name': 'CH2 V High',
            'phrase': 'Voltage at high water level'
        },
        {
            'id': 'cal_l2_2',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH2 Level High (cm)',
            'phrase': 'Known water level at high point'
        },
        {
            'id': 'height_2',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH2 Tank Height (cm)',
            'phrase': 'Container height at full capacity'
        },
        {
            'id': 'vol_2',
            'type': 'float',
            'default_value': 50.0,
            'name': 'CH2 Tank Volume (L)',
            'phrase': 'Container volume at full capacity'
        },
        {'type': 'new_line'},

        # --- CH3 ---
        {
            'type': 'message',
            'default_value': '<strong>CH3 Calibration & Tank</strong>'
        },
        {
            'id': 'cal_v1_3',
            'type': 'float',
            'default_value': 0.073,
            'name': 'CH3 V Low',
            'phrase': 'Voltage at low water level'
        },
        {
            'id': 'cal_l1_3',
            'type': 'float',
            'default_value': 0.0,
            'name': 'CH3 Level Low (cm)',
            'phrase': 'Known water level at low point'
        },
        {
            'id': 'cal_v2_3',
            'type': 'float',
            'default_value': 1.216,
            'name': 'CH3 V High',
            'phrase': 'Voltage at high water level'
        },
        {
            'id': 'cal_l2_3',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH3 Level High (cm)',
            'phrase': 'Known water level at high point'
        },
        {
            'id': 'height_3',
            'type': 'float',
            'default_value': 41.0,
            'name': 'CH3 Tank Height (cm)',
            'phrase': 'Container height at full capacity'
        },
        {
            'id': 'vol_3',
            'type': 'float',
            'default_value': 50.0,
            'name': 'CH3 Tank Volume (L)',
            'phrase': 'Container volume at full capacity'
        },
    ],

    'custom_commands': [
        {
            'type': 'message',
            'default_value': '<strong>Quick Calibration</strong><br>'
                             '1. Select channel to calibrate<br>'
                             '2. Set water to a known level (e.g. empty = 0 cm)<br>'
                             '3. Enter that level and press "Calibrate Low"<br>'
                             '4. Fill to a known high level (e.g. 41 cm)<br>'
                             '5. Enter that level and press "Calibrate High"<br>'
                             'The voltage is read automatically from the sensor.'
        },
        {
            'id': 'cal_channel',
            'type': 'select',
            'default_value': '2',
            'options_select': [
                ('0', 'CH0'),
                ('1', 'CH1'),
                ('2', 'CH2'),
                ('3', 'CH3'),
            ],
            'name': 'Channel',
            'phrase': 'ADC channel to calibrate'
        },
        {
            'id': 'cal_level',
            'type': 'float',
            'default_value': 0.0,
            'name': 'Water Level (cm)',
            'phrase': 'Known water level in cm'
        },
        {
            'id': 'calibrate_low',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Calibrate Low Point'
        },
        {
            'id': 'calibrate_high',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Calibrate High Point'
        },
        {
            'id': 'clear_calibration',
            'type': 'button',
            'wait_for_return': True,
            'name': 'Reset Channel to Defaults'
        }
    ]
}


class InputModule(AbstractInput):
    """Read water level from analog pressure sensors via ADS1115 ADC."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.adc = None
        self.analog_in = None
        self.ads = None
        self.adc_gain = None

        # Per-channel calibration + container (set by setup_custom_options)
        for ch in range(4):
            for attr in ('cal_v1', 'cal_l1', 'cal_v2', 'cal_l2', 'height', 'vol'):
                setattr(self, '{}_{}'.format(attr, ch), None)

        # Precomputed slopes/intercepts
        self.slopes = {}
        self.intercepts = {}

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        import adafruit_ads1x15.ads1115 as ADS
        from adafruit_ads1x15.analog_in import AnalogIn
        from adafruit_extended_bus import ExtendedI2C

        self.analog_in = AnalogIn
        self.ads = ADS

        if self.input_dev.adc_gain == 0:
            self.adc_gain = 2 / 3
        else:
            self.adc_gain = self.input_dev.adc_gain

        try:
            self.adc = ADS.ADS1115(
                ExtendedI2C(self.input_dev.i2c_bus),
                address=int(str(self.input_dev.i2c_location), 16))
            # Precompute calibration for all channels
            for ch in range(4):
                self._recalc_slope(ch)
        except Exception as err:
            self.logger.error("Error initializing ADS1115: {}".format(err))

    def _recalc_slope(self, ch):
        """Recalculate slope/intercept for a channel from its calibration data."""
        v1 = getattr(self, 'cal_v1_{}'.format(ch))
        l1 = getattr(self, 'cal_l1_{}'.format(ch))
        v2 = getattr(self, 'cal_v2_{}'.format(ch))
        l2 = getattr(self, 'cal_l2_{}'.format(ch))

        if v1 is None or v2 is None or abs(v2 - v1) < 0.0001:
            self.slopes[ch] = 1.0
            self.intercepts[ch] = 0.0
        else:
            self.slopes[ch] = (l2 - l1) / (v2 - v1)
            self.intercepts[ch] = l1 - (self.slopes[ch] * v1)

        self.logger.debug(
            "CH{} cal: V1={}, L1={}, V2={}, L2={} -> slope={:.4f}, intercept={:.4f}".format(
                ch, v1, l1, v2, l2, self.slopes[ch], self.intercepts[ch]))

    def get_volt_data(self, channel):
        """Read voltage from the specified ADS1115 channel."""
        if not self.adc:
            return None
        adc_channels = [self.ads.P0, self.ads.P1, self.ads.P2, self.ads.P3]
        chan = self.analog_in(self.adc, adc_channels[channel])
        self.adc.gain = self.adc_gain
        return chan.voltage

    def calibrate_low(self, args_dict):
        """Set low calibration point for selected channel."""
        ch = int(args_dict.get('cal_channel', '0'))
        try:
            level = float(args_dict.get('cal_level', '0'))
        except (ValueError, TypeError):
            self.logger.error("Invalid level value")
            return

        voltage = self.get_volt_data(ch)
        if voltage is None:
            self.logger.error("Cannot read ADC channel {}".format(ch))
            return

        setattr(self, 'cal_v1_{}'.format(ch), voltage)
        setattr(self, 'cal_l1_{}'.format(ch), level)
        self.set_custom_option('cal_v1_{}'.format(ch), voltage)
        self.set_custom_option('cal_l1_{}'.format(ch), level)
        self._recalc_slope(ch)
        self.logger.info(
            "CH{} Low calibrated: {:.4f}V = {:.1f}cm".format(ch, voltage, level))

    def calibrate_high(self, args_dict):
        """Set high calibration point for selected channel."""
        ch = int(args_dict.get('cal_channel', '0'))
        try:
            level = float(args_dict.get('cal_level', '0'))
        except (ValueError, TypeError):
            self.logger.error("Invalid level value")
            return

        voltage = self.get_volt_data(ch)
        if voltage is None:
            self.logger.error("Cannot read ADC channel {}".format(ch))
            return

        setattr(self, 'cal_v2_{}'.format(ch), voltage)
        setattr(self, 'cal_l2_{}'.format(ch), level)
        self.set_custom_option('cal_v2_{}'.format(ch), voltage)
        self.set_custom_option('cal_l2_{}'.format(ch), level)
        self._recalc_slope(ch)
        self.logger.info(
            "CH{} High calibrated: {:.4f}V = {:.1f}cm".format(ch, voltage, level))

    def clear_calibration(self, args_dict):
        """Reset selected channel to default calibration."""
        ch = int(args_dict.get('cal_channel', '0'))
        defaults = {
            'cal_v1': 0.073, 'cal_l1': 0.0,
            'cal_v2': 1.216, 'cal_l2': 41.0,
            'height': 41.0, 'vol': 50.0
        }
        for attr, val in defaults.items():
            key = '{}_{}'.format(attr, ch)
            self.delete_custom_option(key)
            self.set_custom_option(key, val)
            setattr(self, key, val)
        self._recalc_slope(ch)
        self.logger.info("CH{} reset to defaults".format(ch))

    def get_measurement(self):
        if not self.adc:
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        for ch in range(4):
            if self.is_enabled(ch):
                voltage = self.get_volt_data(ch)
                if voltage is None:
                    continue

                if ch not in self.slopes:
                    self._recalc_slope(ch)

                level = self.slopes[ch] * voltage + self.intercepts[ch]
                self.value_set(ch, level)

                # Calculate and log volume
                height = getattr(self, 'height_{}'.format(ch), 0)
                vol = getattr(self, 'vol_{}'.format(ch), 0)
                if height and height > 0:
                    volume = level * (vol / height)
                    self.logger.debug(
                        "CH{}: {:.4f}V -> {:.1f}cm -> {:.1f}L".format(
                            ch, voltage, level, volume))
                else:
                    self.logger.debug(
                        "CH{}: {:.4f}V -> {:.1f}cm".format(ch, voltage, level))

        return self.return_dict

# coding=utf-8
#
# ADS1115 Water Level Input
# Specialized ADS1115 input for analog water level/pressure sensors
# (e.g. QDY30A). Reads voltage per channel and converts to water level
# (cm) using 2-point calibration.
#
import copy
import json
import math

from flask_babel import lazy_gettext

from mycodo.inputs.base_input import AbstractInput

# CH0-3: Volume (L) from ADC A0-A3
# CH4-7: Water Level (cm) from ADC A0-A3
measurements_dict = {
    0: {"measurement": "volume", "unit": "l", "name": "CH0 Vol"},
    1: {"measurement": "volume", "unit": "l", "name": "CH1 Vol"},
    2: {"measurement": "volume", "unit": "l", "name": "CH2 Vol"},
    3: {"measurement": "volume", "unit": "l", "name": "CH3 Vol"},
    4: {"measurement": "length", "unit": "cm", "name": "CH0 Level"},
    5: {"measurement": "length", "unit": "cm", "name": "CH1 Level"},
    6: {"measurement": "length", "unit": "cm", "name": "CH2 Level"},
    7: {"measurement": "length", "unit": "cm", "name": "CH3 Level"},
}

# Maximum calibration level (cm) - adjust if needed for larger tanks
MAX_CAL_LEVEL_CM = 500

# Number of ADC channels (A0-A3)
NUM_CHANNELS = 4

# Default calibration values per channel
_DEFAULTS = {
    "cal_v1": 0.073,
    "cal_l1": 0.0,
    "cal_v2": 1.216,
    "cal_l2": 41.0,
    "height": 41.0,
    "vol": 50.0,
}

INPUT_INFORMATION = {
    "input_name_unique": "ADS1115_WATER_LEVEL",
    "input_manufacturer": "Texas Instruments",
    "input_name": "ADS1115: Water Level",
    "input_name_short": "ADS1115 Water Level",
    "input_library": "Adafruit_CircuitPython_ADS1x15",
    "measurements_name": "Water Level",
    "measurements_dict": measurements_dict,
    "message": (
        "Reads analog water level/pressure sensors (e.g. QDY30A) via "
        "ADS1115 ADC. CH0-3 output Volume (L), CH4-7 output Water "
        "Level (cm). Each pair shares the same ADC input: "
        "CH0+CH4=A0, CH1+CH5=A1, CH2+CH6=A2, CH3+CH7=A3. "
        "Enable whichever you need. Calibration and tank setup "
        'is under "Commands" below.'
    ),
    "options_enabled": [
        "measurements_select",
        "i2c_location",
        "adc_gain",
        "period",
        "pre_output",
    ],
    "options_disabled": ["interface"],
    "dependencies_module": [
        ("pip-pypi", "usb.core", "pyusb==1.1.1"),
        ("pip-pypi", "adafruit_extended_bus", "Adafruit-extended-bus==1.0.2"),
        ("pip-pypi", "adafruit_ads1x15", "adafruit-circuitpython-ads1x15==2.2.25"),
    ],
    "interfaces": ["I2C"],
    "i2c_location": ["0x48", "0x49", "0x4A", "0x4B"],
    "i2c_address_editable": False,
    "adc_gain": [
        (0, "2/3 (±6.144 V)"),
        (1, "1 (±4.096 V)"),
        (2, "2 (±2.048 V)"),
        (4, "4 (±1.024 V)"),
        (8, "8 (±0.512 V)"),
        (16, "16 (±0.256 V)"),
    ],
    "custom_options": [],
    "custom_commands": [
        {
            "type": "message",
            "default_value": "<strong>Calibration & Tank Setup</strong><br>"
            "1. Select channel<br>"
            "2. Set water to LOW level, enter cm, press "
            '"Calibrate Low"<br>'
            "3. Set water to HIGH level, enter cm, press "
            '"Calibrate High"<br>'
            "4. Enter tank height and volume, press "
            '"Set Tank Dimensions"<br>'
            "Voltage is read automatically from the sensor.",
        },
        {
            "id": "cal_channel",
            "type": "select",
            "default_value": "2",
            "options_select": [
                ("0", lazy_gettext("A0 (ADC Channel 0)")),
                ("1", lazy_gettext("A1 (ADC Channel 1)")),
                ("2", lazy_gettext("A2 (ADC Channel 2)")),
                ("3", lazy_gettext("A3 (ADC Channel 3)")),
            ],
            "name": lazy_gettext("Channel"),
            "phrase": lazy_gettext("ADC channel to configure"),
        },
        {
            "id": "cal_level",
            "type": "float",
            "default_value": 0.0,
            "name": lazy_gettext("Water Level (cm)"),
            "phrase": lazy_gettext("Known water level in cm for calibration"),
        },
        {
            "id": "calibrate_low",
            "type": "button",
            "wait_for_return": True,
            "name": lazy_gettext("Calibrate Low Point"),
        },
        {
            "id": "calibrate_high",
            "type": "button",
            "wait_for_return": True,
            "name": lazy_gettext("Calibrate High Point"),
        },
        {"type": "new_line"},
        {
            "id": "tank_height",
            "type": "float",
            "default_value": 41.0,
            "name": lazy_gettext("Tank Height (cm)"),
            "phrase": lazy_gettext("Container height at full capacity"),
        },
        {
            "id": "tank_volume",
            "type": "float",
            "default_value": 50.0,
            "name": lazy_gettext("Tank Volume (L)"),
            "phrase": lazy_gettext("Container volume at full capacity"),
        },
        {
            "id": "set_tank",
            "type": "button",
            "wait_for_return": True,
            "name": lazy_gettext("Set Tank Dimensions"),
        },
        {"type": "new_line"},
        {
            "id": "show_cal",
            "type": "button",
            "wait_for_return": True,
            "name": lazy_gettext("Show Current Calibration"),
        },
        {
            "id": "clear_calibration",
            "type": "button",
            "wait_for_return": True,
            "name": lazy_gettext("Reset Channel to Defaults"),
        },
    ],
}


class InputModule(AbstractInput):
    """Read water level from analog pressure sensors via ADS1115 ADC."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.adc = None
        self.analog_in = None
        self.ads = None
        self.adc_gain = None

        # Per-channel calibration data
        self.cal = {}
        for ch in range(NUM_CHANNELS):
            self.cal[ch] = dict(_DEFAULTS)

        self.slopes = {}
        self.intercepts = {}

        if not testing:
            # Load stored calibration from DB
            self._load_stored_options(input_dev)
            self.try_initialize()

    def _load_stored_options(self, input_dev):
        """Load per-channel calibration from custom_options JSON."""
        try:
            stored = json.loads(input_dev.custom_options)
        except (json.JSONDecodeError, TypeError):
            stored = {}
        for ch in range(NUM_CHANNELS):
            for attr, default in _DEFAULTS.items():
                key = "{}_{}".format(attr, ch)
                self.cal[ch][attr] = stored.get(key, default)

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
                address=int(str(self.input_dev.i2c_location), 16),
            )
            for ch in range(NUM_CHANNELS):
                self._recalc_slope(ch)
        except Exception as err:
            self.logger.error("Error initializing ADS1115: {}".format(err))
            # Ensure failed initialization is detectable by later code
            self.adc = None

    def _recalc_slope(self, ch):
        """Recalculate slope/intercept for a channel from its calibration data."""
        v1 = self.cal[ch]["cal_v1"]
        l1 = self.cal[ch]["cal_l1"]
        v2 = self.cal[ch]["cal_v2"]
        l2 = self.cal[ch]["cal_l2"]

        if abs(v2 - v1) < 0.0001:
            self.slopes[ch] = 1.0
            self.intercepts[ch] = 0.0
        else:
            self.slopes[ch] = (l2 - l1) / (v2 - v1)
            self.intercepts[ch] = l1 - (self.slopes[ch] * v1)

        self.logger.debug(
            "A{} cal: {:.4f}V={}cm, {:.4f}V={}cm -> slope={:.4f}".format(
                ch, v1, l1, v2, l2, self.slopes[ch]
            )
        )

    def _get_valid_channel(self, args_dict):
        """
        Parse and validate cal_channel from args_dict.

        Returns the validated channel number (0 to NUM_CHANNELS-1) or None if invalid.
        Logs appropriate error messages for invalid input.
        """
        cal_channel_raw = args_dict.get("cal_channel", "0")
        try:
            ch = int(cal_channel_raw)
        except (ValueError, TypeError):
            self.logger.error("Invalid cal_channel value: %r", cal_channel_raw)
            return None

        if ch < 0 or ch >= NUM_CHANNELS:
            self.logger.error(
                "Calibration channel must be between 0 and {}".format(NUM_CHANNELS - 1)
            )
            return None

        return ch

    def get_volt_data(self, channel):
        """Read voltage from the specified ADS1115 channel."""
        if not self.adc:
            self.logger.error(
                "ADS1115 not initialized; cannot read channel %s", channel
            )
            return None

        # Derive available ADC channels from NUM_CHANNELS to keep a single
        # source of truth for channel count and mapping.
        try:
            adc_channels = [getattr(self.ads, f"P{i}") for i in range(NUM_CHANNELS)]
        except AttributeError as err:
            self.logger.error(
                "ADS1115 channel configuration mismatch for NUM_CHANNELS=%s: %s",
                NUM_CHANNELS,
                err,
            )
            return None

        max_channel_index = len(adc_channels) - 1

        # Normalize and validate channel index
        try:
            channel_index = int(channel)
        except (TypeError, ValueError):
            self.logger.error(
                "Invalid ADC channel value %r; must be an integer between 0 and %d",
                channel,
                max_channel_index,
            )
            return None

        if channel_index < 0 or channel_index >= len(adc_channels):
            self.logger.error(
                "ADC channel %s out of range; must be between 0 and %d",
                channel_index,
                max_channel_index,
            )
            return None

        try:
            chan = self.analog_in(self.adc, adc_channels[channel_index])
            self.adc.gain = self.adc_gain
            return chan.voltage
        except Exception as err:
            self.logger.error("Error accessing ADC channel %s: %s", channel_index, err)
            return None

    def calibrate_low(self, args_dict):
        """Set low calibration point for selected channel."""
        ch = self._get_valid_channel(args_dict)
        if ch is None:
            return

        try:
            level = float(args_dict.get("cal_level", "0"))
        except (ValueError, TypeError):
            self.logger.error("Invalid level value")
            return

        if not math.isfinite(level):
            self.logger.error("Level must be a finite number")
            return

        # Validate calibration level is within reasonable range
        if level < 0 or level > MAX_CAL_LEVEL_CM:
            self.logger.error(
                "Calibration level must be between 0 and {} cm".format(MAX_CAL_LEVEL_CM)
            )
            return

        voltage = self.get_volt_data(ch)
        if voltage is None:
            self.logger.error("Cannot read ADC channel A{}".format(ch))
            return

        self.cal[ch]["cal_v1"] = voltage
        self.cal[ch]["cal_l1"] = level
        self.set_custom_option("cal_v1_{}".format(ch), voltage)
        self.set_custom_option("cal_l1_{}".format(ch), level)
        self._recalc_slope(ch)
        self.logger.info("A{} Low: {:.4f}V = {:.1f}cm".format(ch, voltage, level))

    def calibrate_high(self, args_dict):
        """Set high calibration point for selected channel."""
        ch = self._get_valid_channel(args_dict)
        if ch is None:
            return

        try:
            level = float(args_dict.get("cal_level", "0"))
        except (ValueError, TypeError):
            self.logger.error("Invalid level value")
            return

        if not math.isfinite(level):
            self.logger.error("Level must be a finite number")
            return

        # Validate calibration level is within reasonable range
        if level < 0 or level > MAX_CAL_LEVEL_CM:
            self.logger.error(
                "Calibration level must be between 0 and {} cm".format(MAX_CAL_LEVEL_CM)
            )
            return

        voltage = self.get_volt_data(ch)
        if voltage is None:
            self.logger.error("Cannot read ADC channel A{}".format(ch))
            return

        self.cal[ch]["cal_v2"] = voltage
        self.cal[ch]["cal_l2"] = level
        self.set_custom_option("cal_v2_{}".format(ch), voltage)
        self.set_custom_option("cal_l2_{}".format(ch), level)
        self._recalc_slope(ch)
        self.logger.info("A{} High: {:.4f}V = {:.1f}cm".format(ch, voltage, level))

    def set_tank(self, args_dict):
        """Set tank dimensions for selected channel."""
        ch = self._get_valid_channel(args_dict)
        if ch is None:
            return

        try:
            height = float(args_dict.get("tank_height", "41"))
            volume = float(args_dict.get("tank_volume", "50"))
        except (ValueError, TypeError):
            self.logger.error("Invalid tank dimensions")
            return

        if not math.isfinite(height) or not math.isfinite(volume):
            self.logger.error("Tank dimensions must be finite numbers")
            return

        # Validate tank dimensions are positive
        if height <= 0:
            self.logger.error("Tank height must be greater than 0")
            return
        if volume <= 0:
            self.logger.error("Tank volume must be greater than 0")
            return

        self.cal[ch]["height"] = height
        self.cal[ch]["vol"] = volume
        self.set_custom_option("height_{}".format(ch), height)
        self.set_custom_option("vol_{}".format(ch), volume)
        self.logger.info("A{} Tank: {}cm = {}L".format(ch, height, volume))

    def show_cal(self, args_dict):
        """Show current calibration for selected channel."""
        ch = self._get_valid_channel(args_dict)
        if ch is None:
            return

        c = self.cal[ch]
        self.logger.info(
            "A{}: Low={:.4f}V={:.1f}cm, High={:.4f}V={:.1f}cm, Tank={}cm/{}L".format(
                ch,
                c["cal_v1"],
                c["cal_l1"],
                c["cal_v2"],
                c["cal_l2"],
                c["height"],
                c["vol"],
            )
        )

    def clear_calibration(self, args_dict):
        """Reset selected channel to default calibration."""
        ch = self._get_valid_channel(args_dict)
        if ch is None:
            return

        for attr, val in _DEFAULTS.items():
            key = "{}_{}".format(attr, ch)
            self.set_custom_option(key, val)
            self.cal[ch][attr] = val
        self._recalc_slope(ch)
        self.logger.info("A{} reset to defaults".format(ch))

    def get_measurement(self):
        if not self.adc:
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        # Read each ADC channel once, reuse for volume + level slots
        for adc_ch in range(NUM_CHANNELS):
            vol_slot = adc_ch  # CH0-3 = volume (L)
            lvl_slot = adc_ch + NUM_CHANNELS  # CH4-7 = level (cm)

            vol_enabled = self.is_enabled(vol_slot)
            lvl_enabled = self.is_enabled(lvl_slot)

            if not vol_enabled and not lvl_enabled:
                continue

            voltage = self.get_volt_data(adc_ch)
            if voltage is None:
                continue

            if adc_ch not in self.slopes:
                self._recalc_slope(adc_ch)

            level_cm = self.slopes[adc_ch] * voltage + self.intercepts[adc_ch]

            if lvl_enabled:
                self.value_set(lvl_slot, level_cm)

            if vol_enabled:
                height = self.cal[adc_ch]["height"]
                vol = self.cal[adc_ch]["vol"]
                if height and height > 0:
                    volume = level_cm * (vol / height)
                    self.value_set(vol_slot, volume)
                else:
                    volume = 0.0
                    self.value_set(vol_slot, volume)

                self.logger.debug(
                    "A{}: {:.4f}V -> {:.1f}cm -> {:.1f}L".format(
                        adc_ch, voltage, level_cm, volume
                    )
                )

        return self.return_dict

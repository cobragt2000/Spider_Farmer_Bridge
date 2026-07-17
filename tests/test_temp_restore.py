"""Regression: restoring a temperature sensor must not double-convert.

HA records a device_class=temperature sensor in the *display* unit (°F for
Imperial users) even though our native unit is °C. Restoring last.state
verbatim treated that °F number as °C and re-displayed it as °F — a 80 °F
reading came back as 176 °F, spiking graphs after every reboot.
"""
from types import SimpleNamespace

from custom_components.sf.sensor import SfSensor
from custom_components.sf.entity_defs import SfDef


def _sensor(unit="°C", device_class="temperature", state_class="measurement",
            field="temperature", options=None):
    d = SfDef(
        platform="sensor", field=field, name="Temperature",
        mac="0a1b2c3d4e01", mac_raw="0A1B2C3D4E01",
        device_name="SF Display Panel 4E01", device_model="Display Panel",
        unit=unit, device_class=device_class, state_class=state_class,
        options=options,
    )
    s = SfSensor.__new__(SfSensor)   # bypass __init__ (no bus needed for _restore)
    s.d = d
    s._attr_native_value = None
    return s


def _last(state, unit):
    return SimpleNamespace(state=state, attributes={"unit_of_measurement": unit})


def test_fahrenheit_restore_converts_back_to_native_celsius():
    s = _sensor()
    s._restore(_last("80.06", "°F"))          # was displayed at 80 °F
    # native must be ~26.7 °C, so it re-displays as 80 °F (not 176 °F)
    assert abs(float(s._attr_native_value) - 26.7) < 0.1


def test_celsius_display_restores_unchanged():
    s = _sensor()
    s._restore(_last("24.5", "°C"))            # metric user, no conversion
    assert float(s._attr_native_value) == 24.5


def test_non_temperature_sensor_restored_verbatim():
    # Humidity has no HA unit conversion; restore the value as-is.
    s = _sensor(unit="%", device_class="humidity", field="humidity")
    s._restore(_last("61.0", "%"))
    assert s._attr_native_value == "61.0"


def test_missing_saved_unit_falls_back_to_verbatim():
    s = _sensor()
    last = SimpleNamespace(state="24.5", attributes={})
    s._restore(last)
    assert s._attr_native_value == "24.5"

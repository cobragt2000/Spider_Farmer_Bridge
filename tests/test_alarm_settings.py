"""Alarm thresholds: decode (°C->°F) + read-modify-write encode."""
from custom_components.sf.proxy.normalizer import decode_alarm_settings
from custom_components.sf.proxy.command_handler import build_alarm_settings

# From the 2026-07-20 log (matches the app screenshots).
ALARM = {
    "temp": {"enabled": 0, "vmin": 18.3333, "vmax": 31.1111},      # 65-88 °F
    "humi": {"enabled": 0, "vmin": 40, "vmax": 80},
    "co2": {"enabled": 0, "vmin": 500, "vmax": 1500},
    "tempSoil": {"enabled": 1, "vmin": 18.3333, "vmax": 29.4444},  # 65-85 °F
    "humiSoil": {"enabled": 1, "vmin": 40, "vmax": 60},
    "ECSoil": {"enabled": 1, "vmin": 1.2, "vmax": 2.3},
    "vpd": {"enabled": 0, "vmin": 0.8, "vmax": 1.8},
    "ppfd": {"enabled": 0, "vmax": 800},
    "devOffline": 1, "dehumiWaterFull": 1, "lightTemp": 1, "humiWaterLess": 1,
}


def test_decode_groups_and_temp_to_f():
    d = decode_alarm_settings(ALARM)
    climate = {m["key"]: m for m in d["climate"]}
    assert climate["temp"]["min"] == 65 and climate["temp"]["max"] == 88   # °C->°F
    assert climate["humi"]["min"] == 40 and climate["humi"]["max"] == 80
    assert climate["vpd"]["max"] == 1.8
    assert "min" not in climate["ppfd"] and climate["ppfd"]["max"] == 800    # max-only
    sub = {m["key"]: m for m in d["substrate"]}
    assert sub["tempSoil"]["min"] == 65 and sub["tempSoil"]["max"] == 85
    assert sub["ECSoil"]["min"] == 1.2 and sub["ECSoil"]["enabled"] == 1
    other = {m["key"]: m["enabled"] for m in d["other"]}
    assert other == {"devOffline": 1, "dehumiWaterFull": 1,
                     "lightTemp": 1, "humiWaterLess": 1}


def test_write_roundtrip_rmw_and_temp_to_c():
    d = decode_alarm_settings(ALARM)
    # enable air temp, set 60-90 °F; disable one substrate alarm
    d["climate"][0]["enabled"] = 1
    d["climate"][0]["min"] = 60
    d["climate"][0]["max"] = 90
    d["substrate"][2]["enabled"] = 0   # ECSoil off
    msg = build_alarm_settings("m", "u", d, ALARM)
    assert msg["params"]["keyPath"] == ["alarm"]
    w = msg["params"]["alarm"]
    # temp written back in °C
    assert w["temp"]["enabled"] == 1
    assert abs(w["temp"]["vmin"] - (60 - 32) * 5 / 9) < 1e-3
    assert abs(w["temp"]["vmax"] - (90 - 32) * 5 / 9) < 1e-3
    # RMW: untouched settings preserved
    assert w["humiSoil"] == {"enabled": 1, "vmin": 40, "vmax": 60}
    assert w["devOffline"] == 1
    assert w["ECSoil"]["enabled"] == 0                 # our edit applied
    # exact decode round-trip of the edited temp
    assert decode_alarm_settings(w)["climate"][0]["min"] == 60


def test_other_bool_toggle():
    d = decode_alarm_settings(ALARM)
    for m in d["other"]:
        if m["key"] == "devOffline":
            m["enabled"] = 0
    w = build_alarm_settings("m", "u", d, ALARM)["params"]["alarm"]
    assert w["devOffline"] == 0 and w["lightTemp"] == 1

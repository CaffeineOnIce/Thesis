"""PolluSense Live Calibrated Dashboard.

Subscribes directly to raw MQTT telemetry from the ESP32 ('pollusense/+/raw'),
applies dynamic calibration formulas on the fly, and prints real-time CPCB
concentrations (µg/m³ and mg/m³) and AQI sub-indices in the terminal.
"""

from datetime import datetime, timedelta, timezone
import json
import math
import os
import paho.mqtt.client as mqtt

from calibrate import (
    co_mgm3_from_ppm,
    mq135_trh_factor,
    no2_ugm3_from_ppm,
    ppm_from_ratio,
    rl_effective,
    rs_from_mv,
)

DATA_DIR = os.path.expanduser("~/pollusense")
CAL_PATH = os.path.join(DATA_DIR, "calibration.json")
IST = timezone(timedelta(hours=5, minutes=30))


def calc_sub_index(c, b_low, b_high, i_low, i_high):
    return i_low + ((i_high - i_low) / (b_high - b_low)) * (c - b_low)


def sub_index_pm25(c):
    if c is None or math.isnan(c) or c < 0:
        return None
    if c <= 30:
        return calc_sub_index(c, 0, 30, 0, 50)
    if c <= 60:
        return calc_sub_index(c, 30, 60, 51, 100)
    if c <= 90:
        return calc_sub_index(c, 60, 90, 101, 200)
    if c <= 120:
        return calc_sub_index(c, 90, 120, 201, 300)
    if c <= 250:
        return calc_sub_index(c, 120, 250, 301, 400)
    return calc_sub_index(min(c, 380), 250, 380, 401, 500)


def sub_index_pm10(c):
    if c is None or math.isnan(c) or c < 0:
        return None
    if c <= 50:
        return calc_sub_index(c, 0, 50, 0, 50)
    if c <= 100:
        return calc_sub_index(c, 50, 100, 51, 100)
    if c <= 250:
        return calc_sub_index(c, 100, 250, 101, 200)
    if c <= 350:
        return calc_sub_index(c, 250, 350, 201, 300)
    if c <= 430:
        return calc_sub_index(c, 350, 430, 301, 400)
    return calc_sub_index(min(c, 510), 430, 510, 401, 500)


def sub_index_no2(c):
    if c is None or math.isnan(c) or c < 0:
        return None
    if c <= 40:
        return calc_sub_index(c, 0, 40, 0, 50)
    if c <= 80:
        return calc_sub_index(c, 40, 80, 51, 100)
    if c <= 180:
        return calc_sub_index(c, 80, 180, 101, 200)
    if c <= 280:
        return calc_sub_index(c, 180, 280, 201, 300)
    if c <= 400:
        return calc_sub_index(c, 280, 400, 301, 400)
    return calc_sub_index(min(c, 500), 400, 500, 401, 500)


def sub_index_co(c):
    if c is None or math.isnan(c) or c < 0:
        return None
    if c <= 1.0:
        return calc_sub_index(c, 0.0, 1.0, 0, 50)
    if c <= 2.0:
        return calc_sub_index(c, 1.0, 2.0, 51, 100)
    if c <= 10.0:
        return calc_sub_index(c, 2.0, 10.0, 101, 200)
    if c <= 17.0:
        return calc_sub_index(c, 10.0, 17.0, 201, 300)
    if c <= 34.0:
        return calc_sub_index(c, 17.0, 34.0, 301, 400)
    return calc_sub_index(min(c, 50.0), 34.0, 50.0, 401, 500)


def get_aqi_category(aqi):
    if aqi is None:
        return "Unknown"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Satisfactory"
    if aqi <= 200:
        return "Moderate"
    if aqi <= 300:
        return "Poor"
    if aqi <= 400:
        return "Very Poor"
    return "Severe"


def on_connect(client, userdata, flags, reason_code, properties=None):
    print("\n========================================================")
    print("  POLLUSENSE LIVE CALIBRATED DASHBOARD")
    print("  Listening to raw ESP32 data on pollusense/+/raw...")
    print("========================================================\n")
    client.subscribe("pollusense/+/raw")


def on_message(client, userdata, msg):
    try:
        if not os.path.isfile(CAL_PATH):
            print(f"Warning: {CAL_PATH} not found. Using default calibration.")
            cal = {
                "mq135_rl": 1000,
                "mq7_rl": 10000,
                "mq135_r0": 4930.0,
                "mq7_r0": 1800.0,
                "no2_m": -0.4282,
                "no2_b": -1.6500,
                "co_m": -1.518,
                "co_b": 1.9958,
            }
        else:
            cal = json.load(open(CAL_PATH))

        d = json.loads(msg.payload.decode())

        rl135 = rl_effective(cal.get("mq135_rl", 1000))
        rl7 = rl_effective(cal.get("mq7_rl", 10000))

        t, h = d.get("temp"), d.get("rh")
        mv135, mv7 = d.get("mq135_mv"), d.get("mq7_mv")
        pm25, pm10 = d.get("pm25"), d.get("pm10")

        rs135 = rs_from_mv(mv135, rl135)
        rs7 = rs_from_mv(mv7, rl7)

        no2_ugm3 = float("nan")
        if not math.isnan(rs135) and t is not None and h is not None:
            ratio135 = (
                rs135
                / mq135_trh_factor(t, h)
                / cal.get("mq135_r0", 4930.0)
            )
            no2_ugm3 = no2_ugm3_from_ppm(
                ppm_from_ratio(
                    ratio135,
                    cal.get("no2_m", -0.4282),
                    cal.get("no2_b", -1.6500),
                )
            )

        co_mgm3 = float("nan")
        if not math.isnan(rs7):
            ratio7 = rs7 / cal.get("mq7_r0", 1800.0)
            co_mgm3 = co_mgm3_from_ppm(
                ppm_from_ratio(
                    ratio7, cal.get("co_m", -1.518), cal.get("co_b", 1.9958)
                )
            )

        s_pm25 = sub_index_pm25(pm25)
        s_pm10 = sub_index_pm10(pm10)
        s_no2 = sub_index_no2(no2_ugm3)
        s_co = sub_index_co(co_mgm3)

        subs = [x for x in [s_pm25, s_pm10, s_no2, s_co] if x is not None]
        overall_aqi = round(max(subs)) if subs else None

        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        print("============================================================")
        print(
            f" [{now_str}] Packet #{d.get('seq')} from Device '{d.get('device_id')}'"
        )
        print("============================================================")
        print(
            f"  [+] PM 2.5 (CPCB)     : {pm25} µg/m³  (Sub-Index: {round(s_pm25) if s_pm25 else 'N/A'})"
        )
        print(
            f"  [+] PM 10  (CPCB)     : {pm10} µg/m³  (Sub-Index: {round(s_pm10) if s_pm10 else 'N/A'})"
        )
        print(
            f"  [+] Temperature       : {t} °C | Humidity: {h} %"
        )
        print(
            f"  [+] MQ-135 Voltage    : {mv135} mV  ->  Rs: {round(rs135) if not math.isnan(rs135) else 'N/A'} Ω"
        )
        print(
            f"  --> Calibrated NO2    : {round(no2_ugm3, 2) if not math.isnan(no2_ugm3) else 'N/A'} µg/m³  (Sub-Index: {round(s_no2) if s_no2 else 'N/A'})"
        )
        print(
            f"  [+] MQ-7 Voltage      : {mv7} mV  ->  Rs: {round(rs7) if not math.isnan(rs7) else 'N/A'} Ω"
        )
        print(
            f"  --> Calibrated CO     : {round(co_mgm3, 3) if not math.isnan(co_mgm3) else 'N/A'} mg/m³   (Sub-Index: {round(s_co) if s_co else 'N/A'})"
        )
        print("------------------------------------------------------------")
        print(
            f"  [OVERALL CPCB AQI]    : {overall_aqi}  [Category: {get_aqi_category(overall_aqi)}]"
        )
        print(
            "============================================================\n"
        )
    except Exception as e:
        print(f"[Live Monitor Error] {e}")


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("localhost", 1883, 60)
    client.loop_forever()

"""15-Minute Rolling Mean Aggregator with Direct CSV Storage.
Runs every 15 minutes (:01, :16, :31, :46) via systemd timer.
"""
import json, math, sqlite3, os, csv, time
from datetime import datetime, timezone, timedelta
from calibrate import (rl_effective, rs_from_mv, mq135_trh_factor,
                       ppm_from_ratio, no2_ugm3_from_ppm, co_mgm3_from_ppm)
DB = os.path.expanduser("~/pollusense/edge/data.db")
CAL_PATH = os.path.expanduser("~/pollusense/edge/calibration.json")
CSV_OUT = os.path.expanduser("~/pollusense/edge/records_15min.csv")
CAL = json.load(open(CAL_PATH))
IST = timezone(timedelta(hours=5, minutes=30))
def calc_mean(vals):
    valid = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return round(float(sum(valid) / len(valid)), 2) if valid else None
def main(now=None):
    now = int(now or time.time())
    end = now - (now % 900)            # 15-minute window boundary
    start = end - 900
    
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ? ORDER BY ts",
                       (start, end)).fetchall()
                       
    if not rows:
        print(f"[{datetime.now()}] No records found in window {start} to {end}")
        return
    msgs = [json.loads(p) for (p,) in rows]
    
    pm25_vals = [d.get("pm25") for d in msgs]
    pm10_vals = [d.get("pm10") for d in msgs]
    temp_vals = [d.get("temp") for d in msgs]
    rh_vals   = [d.get("rh") for d in msgs]
    m135_vals = [d.get("mq135_mv") for d in msgs]
    mq7_vals  = [d.get("mq7_mv") for d in msgs]
    
    # 1. Compute Basic Means across the 15-minute window
    mean_pm25 = calc_mean(pm25_vals)
    mean_pm10 = calc_mean(pm10_vals)
    mean_temp = calc_mean(temp_vals)
    mean_rh   = calc_mean(rh_vals)
    mean_m135 = calc_mean(m135_vals)
    mean_mq7  = calc_mean(mq7_vals)
    
    # 2. Dynamic Calibration from Mean Voltages
    rl135 = rl_effective(CAL["mq135_rl"])
    rl7   = rl_effective(CAL["mq7_rl"])
    
    rs135 = rs_from_mv(mean_m135, rl135)
    rs7   = rs_from_mv(mean_mq7, rl7)
    
    no2_ugm3 = None
    if not math.isnan(rs135) and mean_temp is not None and mean_rh is not None:
        ratio135 = rs135 / mq135_trh_factor(mean_temp, mean_rh) / CAL["mq135_r0"]
        no2_ugm3 = round(no2_ugm3_from_ppm(ppm_from_ratio(ratio135, CAL["no2_m"], CAL["no2_b"])), 2)
        
    co_mgm3 = None
    if not math.isnan(rs7):
        ratio7 = rs7 / CAL["mq7_r0"]
        co_mgm3 = round(co_mgm3_from_ppm(ppm_from_ratio(ratio7, CAL["co_m"], CAL["co_b"])), 3)
    dt_utc = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    dt_ist = datetime.fromtimestamp(end, tz=IST).strftime("%Y-%m-%d %H:%M:%S")
    
    record = {
        "datetime_ist": dt_ist,
        "datetime_utc": dt_utc,
        "ts": end,
        "device_id": msgs[0].get("device_id", CAL.get("device_id", "ps01")),
        "minutes_counted": len(msgs),
        "pm25": mean_pm25,
        "pm10": mean_pm10,
        "temp": mean_temp,
        "rh": mean_rh,
        "mq135_mv": mean_m135,
        "mq7_mv": mean_mq7,
        "no2_ugm3": no2_ugm3,
        "co_mgm3": co_mgm3
    }
    
    # 3. Direct CSV Logging (Appends to continuous CSV file)
    file_exists = os.path.isfile(CSV_OUT)
    fields = ["datetime_ist", "datetime_utc", "ts", "device_id", "minutes_counted",
              "pm25", "pm10", "temp", "rh", "mq135_mv", "mq7_mv", "no2_ugm3", "co_mgm3"]
              
    with open(CSV_OUT, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)
        
    # Also record in SQLite for fast range queries
    con.execute("""CREATE TABLE IF NOT EXISTS records_15min (
        ts INTEGER PRIMARY KEY, datetime_ist TEXT, device_id TEXT, record TEXT
    )""")
    con.execute("INSERT OR REPLACE INTO records_15min VALUES (?,?,?,?)",
                (end, dt_ist, record["device_id"], json.dumps(record)))
    con.commit()
    
    print(f"[{dt_ist}] Stored 15-min rolling mean to {CSV_OUT}: {record}")
if __name__ == "__main__":
    main()

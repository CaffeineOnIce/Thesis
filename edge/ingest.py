import json, sqlite3, time, os
from datetime import datetime, timezone, timedelta
import paho.mqtt.client as mqtt
DB = os.path.expanduser("~/pollusense/edge/data.db")
IST = timezone(timedelta(hours=5, minutes=30))
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS raw_1min (
    device_id TEXT,
    boot_id INTEGER,
    seq INTEGER,
    ts INTEGER,
    datetime_utc TEXT,
    datetime_ist TEXT,
    rx_ts REAL,
    payload TEXT
)""")
con.execute("CREATE INDEX IF NOT EXISTS ix_raw_ts ON raw_1min(ts)")
con.execute("CREATE INDEX IF NOT EXISTS ix_raw_date ON raw_1min(datetime_ist)")
con.commit()
def on_connect(client, userdata, flags, reason_code, properties=None):
    print("[Ingest] Connected to local broker. Subscribed to pollusense/+/raw")
    client.subscribe("pollusense/+/raw", qos=0)
def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        d = json.loads(payload_str)
        pkt_ts = d.get("ts")
        if not pkt_ts or pkt_ts < 1700000000:
            pkt_ts = int(time.time())
            
        dt_utc = datetime.fromtimestamp(pkt_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        dt_ist = datetime.fromtimestamp(pkt_ts, tz=IST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"[Ingest Error] {e}")
        return
    con.execute("""INSERT INTO raw_1min 
                   (device_id, boot_id, seq, ts, datetime_utc, datetime_ist, rx_ts, payload)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (d.get("device_id"), d.get("boot_id"), d.get("seq"), pkt_ts,
                 dt_utc, dt_ist, time.time(), payload_str))
    con.commit()
    print(f"[{dt_ist}] Stored packet #{d.get('seq')} from {d.get('device_id')}")
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-ingest")
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_forever()

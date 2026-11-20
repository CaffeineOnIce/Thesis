import json, sqlite3, time
import paho.mqtt.client as mqtt

DB = "/home/pi/pollusense/data.db"
MQTT_USER, MQTT_PASS = "pollusense", "CHANGE_ME"

con = sqlite3.connect(DB, check_same_thread=False)
con.execute("""CREATE TABLE IF NOT EXISTS raw_1min (
    device_id TEXT, boot_id INTEGER, seq INTEGER, ts INTEGER,
    rx_ts REAL, payload TEXT)""")
con.execute("CREATE INDEX IF NOT EXISTS ix_raw_ts ON raw_1min(ts)")
con.commit()

def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe("pollusense/+/raw", qos=0)

def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload)
    except ValueError:
        return
    con.execute("INSERT INTO raw_1min VALUES (?,?,?,?,?,?)",
                (d.get("device_id"), d.get("boot_id"), d.get("seq"), d.get("ts"),
                 time.time(), msg.payload.decode()))
    con.commit()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-ingest")
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_forever()

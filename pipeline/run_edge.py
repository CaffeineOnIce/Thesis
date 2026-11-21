"""Edge mode (Pi): local rec15 -> process -> publish cleaned record to the VM (queued while the link is down).
Logs when each record was ready on the Pi, for E3/E4.  Run: python -m pipeline.run_edge"""
import json, sqlite3, time
import paho.mqtt.client as mqtt
from pipeline.core import State, process
from pipeline.uplink import Uplink

CFG = json.load(open("pipeline_config.json"))
st = State(f"models/{CFG['model']}.joblib", detector=CFG["detector"])
log = sqlite3.connect("edge_log.db", check_same_thread=False)
log.execute("CREATE TABLE IF NOT EXISTS edge_log (ts INTEGER PRIMARY KEY, received_at REAL, done_at REAL, t_total_ms REAL, record TEXT)")

cloud = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-edge-uplink")
cloud.username_pw_set(CFG["vm_user"], CFG["vm_pass"])
cloud.tls_set(ca_certs=CFG["vm_ca"])
cloud.connect_async(CFG["vm_host"], 8883)
cloud.loop_start()                                   # reconnects by itself after an outage
up = Uplink(cloud, "edge_queue.db")

def on_message(client, userdata, msg):
    t_rx = time.time()
    rec = json.loads(msg.payload)
    out = process(rec, st)
    t_done = time.time()
    log.execute("INSERT OR REPLACE INTO edge_log VALUES (?,?,?,?,?)",
                (rec["ts"], t_rx, t_done, out["t_total_ms"], json.dumps(out)))
    log.commit()
    up.send(f"pollusense/{rec['device_id']}/clean", json.dumps(out))

def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe("pollusense/+/rec15", qos=1)

local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-edge")
local.username_pw_set(CFG["local_user"], CFG["local_pass"])
local.on_connect, local.on_message = on_connect, on_message
local.connect("localhost", 1883)
local.loop_forever()

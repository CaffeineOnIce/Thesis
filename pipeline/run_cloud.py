"""Cloud mode, VM side: raw rec15 from the Pi -> process -> log.  Run on the VM: python -m pipeline.run_cloud"""
import json, sqlite3, time
import paho.mqtt.client as mqtt
from pipeline.core import State, process

CFG = json.load(open("pipeline_config.json"))
st = State(f"models/{CFG['model']}.joblib", detector=CFG["detector"])
log = sqlite3.connect("cloud_log.db", check_same_thread=False)
log.execute("CREATE TABLE IF NOT EXISTS cloud_log (ts INTEGER PRIMARY KEY, received_at REAL, done_at REAL, t_total_ms REAL, record TEXT)")

def on_message(client, userdata, msg):
    t_rx = time.time()
    rec = json.loads(msg.payload)
    out = process(rec, st)
    log.execute("INSERT OR REPLACE INTO cloud_log VALUES (?,?,?,?,?)",
                (rec["ts"], t_rx, time.time(), out["t_total_ms"], json.dumps(out)))
    log.commit()

def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe("pollusense/+/rec15raw", qos=1)

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="vm-cloud")
c.username_pw_set(CFG["vm_user"], CFG["vm_pass"])
c.tls_set(ca_certs=CFG["vm_ca"])
c.on_connect, c.on_message = on_connect, on_message
c.connect(CFG["vm_host"], 8883)
c.loop_forever()

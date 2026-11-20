"""Cloud mode, Pi side: forward each raw rec15 to the VM unchanged (queued while the link is down).
Run: python -m pipeline.forward_raw"""
import json
import paho.mqtt.client as mqtt
from pipeline.uplink import Uplink

CFG = json.load(open("pipeline_config.json"))
cloud = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-forwarder-uplink")
cloud.username_pw_set(CFG["vm_user"], CFG["vm_pass"])
cloud.tls_set(ca_certs=CFG["vm_ca"])
cloud.connect_async(CFG["vm_host"], 8883)
cloud.loop_start()
up = Uplink(cloud, "forward_queue.db")

def on_message(client, userdata, msg):
    rec = json.loads(msg.payload)
    up.send(f"pollusense/{rec['device_id']}/rec15raw", msg.payload.decode())

def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe("pollusense/+/rec15", qos=1)

local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi-forwarder")
local.username_pw_set(CFG["local_user"], CFG["local_pass"])
local.on_connect, local.on_message = on_connect, on_message
local.connect("localhost", 1883)
local.loop_forever()

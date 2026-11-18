# PolluSense Node & Edge Gateway: Complete Build & Operation Guide
**IEEE WoWMoM 2027 Experimental Setup & Deployment Manual**

---

## Table of Contents
1. [System Architecture Overview](#1-system-architecture-overview)
2. [Circuit Design & Hardware Wiring](#2-circuit-design--hardware-wiring)
3. [Network & Dedicated SSH Access Protocol](#3-network--dedicated-ssh-access-protocol)
4. [ESP32 Firmware: Raw Telemetry & MQTT Publisher](#4-esp32-firmware-raw-telemetry--mqtt-publisher)
5. [Raspberry Pi MQTT Broker & Raw Ingestion Service](#5-raspberry-pi-mqtt-broker--raw-ingestion-service)
6. [Dynamic Calibration Engine & CPCB Calculations](#6-dynamic-calibration-engine--cpcb-calculations)
7. [15-Minute Aggregation: Rolling Mean & Direct CSV Storage](#7-15-minute-aggregation-rolling-mean--direct-csv-storage)
8. [Live Diagnostics, Maintenance & CSV Export Tools](#8-live-diagnostics-maintenance--csv-export-tools)

---

## 1. System Architecture Overview

PolluSense decouples low-cost edge sensing into two distinct tiers:
1. **ESP32 Sensing Node (Pure Digitizer)**: Runs bare-metal firmware sampling physical sensors every 5 seconds, packaging 1-minute averages of **raw electrical voltages ($\text{mV}$) and particle counts ($\mu\text{g/m}^3$)** into compact JSON payloads. It transmits these packets over MQTT. No heater PWM cycles or static calibrations are hardcoded on the microcontroller.
2. **Raspberry Pi 5 Gateway (Edge Compute & Calibration Engine)**: Receives raw telemetry, synchronizes authoritative timestamps (UTC and IST), stores raw measurements in SQLite, applies environmental compensation and sensor resistance curves ($R_s/R_0$), calculates **15-minute basic rolling means**, and writes calibrated records **directly into a continuous CSV file** on the Pi.

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                     ESP32 NODE (Sensor Tier)                     │
 │  - PMS7003 (UART) : PM2.5, PM10                                  │
 │  - DHT11   (GPIO) : Temperature, Relative Humidity               │
 │  - MQ-135  (ADC1) : Raw AO Voltage (mV) for NO2                  │
 │  - MQ-7    (ADC1) : Raw AO Voltage (mV) for CO (Direct 5V)       │
 └─────────────────────────────────┬────────────────────────────────┘
                                   │ WiFi (802.11 b/g/n)
                                   │ MQTT: pollusense/ps01/raw (Port 1883)
                                   ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                 RASPBERRY PI 5 (Edge Gateway Tier)               │
 │  - Mosquitto Broker (Port 1883, 0.0.0.0)                         │
 │  - ps-ingest.service    -> Saves raw 1-min packets to data.db    │
 │  - Dynamic Calibration  -> Rs, R0, T/RH compensation, ppm -> CPCB│
 │  - ps-aggregate.timer   -> 15-min Basic Mean -> records_15min.csv│
 │  - Dedicated Access     -> pollusense-edge.local / 192.168.1.50  │
 └──────────────────────────────────────────────────────────────────┘
```

---

## 2. Circuit Design & Hardware Wiring

### 2.1 Golden Hardware Rules
1. **ADC1 Only**: All analog sensor inputs must strictly connect to **ADC1** pins (GPIO 32–39). **ADC2 cannot be used** because the ESP32 internal Wi-Fi subsystem locks ADC2 hardware channels.
2. **Voltage Divider**: The ESP32 ADC cannot tolerate voltages above 3.3 V. Because MQ modules run at 5.0 V rail voltage, their analog outputs ($AO$) go through a **$100\text{ k}\Omega / 100\text{ k}\Omega$ voltage divider** (with a $100\text{ nF}$ ceramic decoupling capacitor to GND) stepping down $0 - 5.0\text{ V}$ to $0 - 2.5\text{ V}$. The firmware multiplies by $2.0$ to recover true module $V_{\text{out}}$.
3. **Common Ground & Shared 5V Rail**: All grounds (ESP32 GND, sensor GNDs, 5V power adapter GND) must be joined into a single ground plane. Place a $470\ \mu\text{F}$ electrolytic capacitor across the 5V rail to prevent voltage dips.
4. **No Heater Control Pin / Direct 5V**: The heating cycle and MOSFET gate switching have been completely removed. Both the MQ-135 and MQ-7 heaters connect directly to the 5V rail and GND for continuous, steady operation.

### 2.2 Complete Pin Connection Table

| Sensor Pin | ESP32 Pin / Rail | Intermediary Circuit | Function / Purpose |
| :--- | :--- | :--- | :--- |
| **PMS7003 TX** | **GPIO 16 (RX2)** | Direct | 3.3V UART (9600 baud, 8N1) |
| **PMS7003 RX** | **GPIO 17 (TX2)** | Direct | UART return (optional) |
| **PMS7003 VCC**| **5V Rail** | Direct | Fan & laser require 5V supply |
| **PMS7003 GND**| **Common GND** | Direct | Common reference |
| **DHT11 DATA** | **GPIO 4** | $10\text{ k}\Omega$ pull-up to 3.3V | Single-wire digital protocol |
| **DHT11 VCC**  | **3.3V Pin** | Direct | 3.3V logic level |
| **DHT11 GND**  | **Common GND** | Direct | Common reference |
| **MQ-135 AO**  | **GPIO 34 (ADC1)**| $100\text{k}/100\text{k}$ divider + $100\text{nF}$ | Halves 0–5V to 0–2.5V safe ADC |
| **MQ-135 VCC** | **5V Rail** | Direct | Sensor internal heater supply |
| **MQ-135 GND** | **Common GND** | Direct | Common reference |
| **MQ-7 AO**    | **GPIO 35 (ADC1)**| $100\text{k}/100\text{k}$ divider + $100\text{nF}$ | Halves 0–5V to 0–2.5V safe ADC |
| **MQ-7 VCC/H1**| **5V Rail** | Direct | Sensor power and continuous heater |
| **MQ-7 GND/H2**| **Common GND** | Direct | Common reference |

---

## 3. Network & Dedicated SSH Access Protocol

When moving the Raspberry Pi between different Wi-Fi networks (home, lab, phone hotspot), the DHCP IP changes constantly. The following configuration provides three failsafe connection options:

### 3.1 Method A: Zero-Configuration mDNS Hostname (Primary)
Connect directly without knowing any IP address:
```powershell
ssh edgepi2@pollusense-edge.local
```
* **How it works**: Uses the Avahi mDNS daemon. Broadly compatible with Windows 10/11, macOS, and Linux.

### 3.2 Method B: Secondary Permanent IP Alias (`192.168.1.50`)
The Pi maintains its standard dynamic DHCP IP from the router, while a systemd service binds a permanent secondary IP alias (`192.168.1.50/24`) to `wlan0`. If your laptop or lab is on the `192.168.1.x` subnet:
```powershell
ssh edgepi2@192.168.1.50
```

### 3.3 Method C: Emergency Standalone Field Hotspot (`192.168.4.1`)
When conducting outdoor tests with no local Wi-Fi router, the Pi broadcasts its own network:
* **SSID**: `PolluSense-Hotspot`
* **Password**: `pollusense123`
* **Static Pi IP**: `192.168.4.1`
* **Access**: `ssh edgepi2@192.168.4.1`

### 3.4 One-Click Setup Script on the Pi
Run this script on the Pi once to configure all three methods:
```bash
cat <<'EOF' > ~/setup_dedicated_access.sh
#!/usr/bin/env bash
set -e
sudo hostnamectl set-hostname pollusense-edge
sudo apt update && sudo apt install -y avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon

# Bind permanent IP alias 192.168.1.50
sudo tee /etc/systemd/system/permanent-ip-alias.service > /dev/null <<SERVICE_EOF
[Unit]
Description=Permanent Static IP Alias on wlan0
After=network.target network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip addr add 192.168.1.50/24 dev wlan0 label wlan0:alias || true'
ExecStop=/bin/sh -c 'ip addr del 192.168.1.50/24 dev wlan0:alias || true'

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo systemctl daemon-reload
sudo systemctl enable --now permanent-ip-alias.service
echo "Dedicated access configured successfully!"
EOF
chmod +x ~/setup_dedicated_access.sh && ~/setup_dedicated_access.sh
```

---

## 4. ESP32 Firmware: Raw Telemetry & MQTT Publisher

### 4.1 Specification
* **Target Board**: ESP32 Dev Module (Core 3.x)
* **Libraries**: `PubSubClient` by Nick O'Leary, `DHT sensor library` by Adafruit, `Adafruit Unified Sensor`.
* **Output Payload**: Pure raw parameters without static concentration conversions.

### 4.2 Raw JSON Schema (Topic: `pollusense/<DEVICE_ID>/raw`)
```json
{
  "device_id": "ps01",
  "boot_id": 3211024503,
  "seq": 42,
  "ts": 1794998476,
  "iso_ts": "2026-11-18T16:45:00Z",
  "uptime_s": 2520,
  "rssi": -48,
  "pm25": 42.5,
  "pm10": 58.1,
  "pm_frames": 60,
  "temp": 28.5,
  "rh": 52.0,
  "mq135_mv": 1050.2,
  "mq7_mv": 1012.8
}
```

### 4.3 Complete Arduino-ESP32 Sketch (`pollusense_node.ino`)
*(Also saved in your project folder as `pollusense_node.ino`)*:

```cpp
// PolluSense Node Firmware - Arduino-ESP32 Core 3.x
// Pure Raw Telemetry Mode (No Heater Pin / Direct 5V Sensing)
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <time.h>
#include <esp_system.h>

// ---------- Configuration Parameters ----------
const char* WIFI_SSID = "NM_Lab";
const char* WIFI_PASS = "nm@123456";
const char* MQTT_HOST = "192.168.0.104";   // Raspberry Pi IP address
const int   MQTT_PORT = 1883;
const char* MQTT_USER = "pollusense";
const char* MQTT_PASS = "CHANGE_ME";
const char* DEVICE_ID = "ps01";
// ----------------------------------------------

#define PMS_RX_PIN 16
#define PMS_TX_PIN 17
#define DHT_PIN 4
#define MQ135_PIN 34
#define MQ7_PIN 35
const float DIV_RATIO = 2.0f;             // 100k/100k voltage divider multiplier

DHT dht(DHT_PIN, DHT11);
WiFiClient net;
PubSubClient mqtt(net);
String topic;

uint32_t bootId, seq = 0;
uint32_t pm25Sum = 0, pm10Sum = 0; 
uint16_t pmN = 0;
float mq135Sum = 0; uint16_t mq135N = 0;
float mq7Sum   = 0; uint16_t mq7N   = 0;

uint32_t lastPublish = 0, lastSample = 0;
uint32_t lastWifiTry = 0, lastMqttTry = 0;

float readMv(int pin) {
  uint32_t s = 0;
  for (int i = 0; i < 64; i++) s += analogReadMilliVolts(pin);
  return (s / 64.0f) * DIV_RATIO;
}

String num(float v, int d = 1) { 
  return isnan(v) ? String("null") : String(v, d); 
}

String getIsoTimestamp(time_t t) {
  if (t < 1700000000) return "null";
  struct tm timeinfo;
  gmtime_r(&t, &timeinfo);
  char buf[30];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return "\"" + String(buf) + "\"";
}

void readPMS() {
  static uint8_t buf[32]; 
  static uint8_t idx = 0;
  while (Serial2.available()) {
    uint8_t c = Serial2.read();
    if (idx == 0 && c != 0x42) continue;
    if (idx == 1 && c != 0x4D) { idx = 0; continue; }
    buf[idx++] = c;
    if (idx < 32) continue;
    idx = 0;
    
    uint16_t sum = 0;
    for (int i = 0; i < 30; i++) sum += buf[i];
    if (sum != (uint16_t)((buf[30] << 8) | buf[31])) continue;
    
    pm25Sum += (buf[12] << 8) | buf[13]; // PM2.5 in µg/m³
    pm10Sum += (buf[14] << 8) | buf[15]; // PM10 in µg/m³
    pmN++;
  }
}

void keepConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiTry > 10000) { 
      WiFi.reconnect(); 
      lastWifiTry = millis(); 
    }
    return;
  }
  if (!mqtt.connected() && millis() - lastMqttTry > 5000) {
    lastMqttTry = millis();
    Serial.print(F("[MQTT] Connecting to Pi ("));
    Serial.print(MQTT_HOST);
    Serial.print(F(")... "));
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS)) {
      Serial.println(F("CONNECTED!"));
    } else {
      Serial.print(F("FAILED, rc = "));
      Serial.println(mqtt.state());
    }
  }
}

void publishMinute() {
  float pm25 = pmN > 0 ? (pm25Sum / (float)pmN) : NAN;
  float pm10 = pmN > 0 ? (pm10Sum / (float)pmN) : NAN;
  float t = dht.readTemperature(), h = dht.readHumidity();
  float mq135 = mq135N ? (mq135Sum / mq135N) : NAN;
  float mq7   = mq7N   ? (mq7Sum / mq7N)     : NAN;
  time_t now = time(nullptr);
  
  String js = "{\"device_id\":\"" + String(DEVICE_ID) + "\"";
  js += ",\"boot_id\":" + String(bootId);
  js += ",\"seq\":" + String(seq++);
  js += ",\"ts\":" + (now > 1700000000 ? String((long)now) : String("null"));
  js += ",\"iso_ts\":" + getIsoTimestamp(now);
  js += ",\"uptime_s\":" + String(millis() / 1000);
  js += ",\"rssi\":" + String(WiFi.RSSI());
  js += ",\"pm25\":" + num(pm25);
  js += ",\"pm10\":" + num(pm10);
  js += ",\"pm_frames\":" + String(pmN);
  js += ",\"temp\":" + num(t);
  js += ",\"rh\":" + num(h);
  js += ",\"mq135_mv\":" + num(mq135);
  js += ",\"mq7_mv\":" + num(mq7) + "}";

  bool published = false;
  if (mqtt.connected()) {
    published = mqtt.publish(topic.c_str(), js.c_str());
  }

  Serial.println(F("\n================================================================"));
  Serial.print  (F("         POLLUSENSE RAW REPORT [Seq #")); Serial.print(seq - 1); Serial.println(F("]"));
  Serial.println(F("================================================================"));
  Serial.print  (F("  [Raw] PM 2.5        : ")); Serial.print(num(pm25));  Serial.println(F(" µg/m³"));
  Serial.print  (F("  [Raw] PM 10         : ")); Serial.print(num(pm10));  Serial.println(F(" µg/m³"));
  Serial.print  (F("  [Raw] Temperature   : ")); Serial.print(num(t));     Serial.println(F(" °C"));
  Serial.print  (F("  [Raw] Humidity      : ")); Serial.print(num(h));     Serial.println(F(" %"));
  Serial.print  (F("  [Raw] MQ-135 Voltage: ")); Serial.print(num(mq135)); Serial.println(F(" mV"));
  Serial.print  (F("  [Raw] MQ-7 Voltage  : ")); Serial.print(num(mq7));   Serial.println(F(" mV"));
  Serial.print  (F("  [Raw] Valid Frames  : ")); Serial.println(pmN);
  Serial.println(F("----------------------------------------------------------------"));
  Serial.print  (F("  [MQTT Publish]      : ")); Serial.println(published ? F("SUCCESS") : F("FAILED / Disconnected"));
  Serial.print  (F("  [JSON Payload]      : ")); Serial.println(js);
  Serial.println(F("================================================================\n"));

  pm25Sum = pm10Sum = 0; pmN = 0;
  mq135Sum = 0; mq135N = 0;
  mq7Sum = 0;   mq7N = 0;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial2.begin(9600, SERIAL_8N1, PMS_RX_PIN, PMS_TX_PIN);
  dht.begin();
  
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);
  analogSetPinAttenuation(MQ7_PIN, ADC_11db);

  bootId = esp_random();
  topic = String("pollusense/") + DEVICE_ID + "/raw";
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);

  lastPublish = lastSample = millis();
}

void loop() {
  keepConnected();
  mqtt.loop();
  readPMS();

  if (millis() - lastSample >= 5000) {
    lastSample = millis();
    float curMq135 = readMv(MQ135_PIN);
    mq135Sum += curMq135; mq135N++;

    float curMq7 = readMv(MQ7_PIN);
    mq7Sum += curMq7; mq7N++;

    Serial.print(F("[5s Live] Temp: ")); Serial.print(num(dht.readTemperature()));
    Serial.print(F("°C | RH: ")); Serial.print(num(dht.readHumidity()));
    Serial.print(F("% | MQ135: ")); Serial.print(num(curMq135));
    Serial.print(F("mV | MQ7: ")); Serial.print(num(curMq7));
    Serial.print(F("mV | WiFi: ")); Serial.println(WiFi.status() == WL_CONNECTED ? F("Connected") : F("Connecting"));
  }

  if (millis() - lastPublish >= 60000) {
    lastPublish += 60000;
    publishMinute();
  }
}
```

---

## 5. Raspberry Pi MQTT Broker & Raw Ingestion Service

### 5.1 Mosquitto Broker Configuration
On Raspberry Pi OS (Mosquitto 2.x), the broker binds to `127.0.0.1` by default and rejects remote connections. Run the following on the Pi to enable network listening:

```bash
# Allow external Wi-Fi connections on port 1883
sudo tee /etc/mosquitto/conf.d/pollusense.conf > /dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF

sudo systemctl restart mosquitto
sudo ss -tulpn | grep 1883    # Must show LISTEN 0.0.0.0:1883
```

### 5.2 Raw Ingestion Worker (`~/pollusense/ingest.py`)
This daemon consumes packets from `pollusense/+/raw` and writes them into SQLite (`data.db`). If the ESP32 loses time synchronization, the script automatically uses the Pi's local clock to ensure zero timestamp gaps.

```bash
cat <<'EOF' > ~/pollusense/ingest.py
import json, sqlite3, time, os
from datetime import datetime, timezone, timedelta
import paho.mqtt.client as mqtt

DB = os.path.expanduser("~/pollusense/data.db")
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
EOF
```

### 5.3 Systemd Service Configuration
```bash
sudo tee /etc/systemd/system/ps-ingest.service > /dev/null <<EOF
[Unit]
Description=PolluSense Raw Ingest Service
After=network-online.target mosquitto.service

[Service]
User=edgepi2
WorkingDirectory=/home/edgepi2/pollusense
ExecStart=/home/edgepi2/venv/bin/python /home/edgepi2/pollusense/ingest.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ps-ingest
systemctl status ps-ingest
```

---

## 6. Dynamic Calibration Engine & CPCB Calculations

### 6.1 Calibration Mathematical Equations
1. **Effective Load Resistance ($R_{L,\text{eff}}$)**:
   The physical $100\text{k}\Omega + 100\text{k}\Omega = 200\text{ k}\Omega$ voltage divider sits in parallel with the module load resistor $R_L$:
   $$R_{L,\text{eff}} = \frac{R_L \times 200000}{R_L + 200000}$$
2. **True Sensor Resistance ($R_s$)**:
   From module output voltage $V_{\text{out}} = \frac{\text{mV}}{1000}$ under supply $V_c = 5.0\text{ V}$:
   $$R_s = R_{L,\text{eff}} \times \left(\frac{V_c - V_{\text{out}}}{V_{\text{out}}}\right)$$
3. **Temperature & Humidity Compensation (MQ-135)**:
   $$f(T, \text{RH}) = 0.00035 \cdot T^2 - 0.02718 \cdot T + 1.39538 - (\text{RH} - 33.0) \cdot 0.0018$$
   $$\text{ratio} = \frac{R_s}{f(T, \text{RH}) \times R_0}$$
4. **Gas Concentration Curves (Power-Law Form)**:
   $$\log_{10}(\text{ppm}) = m \cdot \log_{10}(\text{ratio}) + b \iff \text{ppm} = 10^{(m \cdot \log_{10}(\text{ratio}) + b)}$$
   * **MQ-7 (CO)**: $m = -1.518, \quad b = \log_{10}(99.042) = 1.9958$
   * **MQ-135 ($\text{NO}_2$)**: $m = -0.4282, \quad b = -1.6500$ (ambient baseline calibration for realistic 20–50 $\mu\text{g/m}^3$)
5. **Conversion to CPCB Standard Units**:
   * **$\text{CO}$**: $\text{mg/m}^3 = \text{ppm} \times \frac{28.01}{24.45} \approx \text{ppm} \times 1.145$
   * **$\text{NO}_2$**: $\mu\text{g/m}^3 = \text{ppm} \times \frac{46.01 \times 1000}{24.45} \approx \text{ppm} \times 1880.0$

### 6.2 Configuration Files
Create the hardware and calibration profiles on the Pi:

```bash
# ~/pollusense/hardware.json
cat <<'EOF' > ~/pollusense/hardware.json
{
  "mq135_rl": 1000,
  "mq7_rl": 10000
}
EOF

# ~/pollusense/calibration.json
cat <<'EOF' > ~/pollusense/calibration.json
{
  "device_id": "ps01",
  "mq135_rl": 1000,
  "mq7_rl": 10000,
  "mq135_r0": 4930.0,
  "mq7_r0": 1800.0,
  "no2_m": -0.4282,
  "no2_b": -1.6500,
  "co_m": -1.518,
  "co_b": 1.9958,
  "mqtt_user": "pollusense",
  "mqtt_pass": "CHANGE_ME"
}
EOF
```

### 6.3 Mathematical Engine Script (`~/pollusense/calibrate.py`)
```bash
cat <<'EOF' > ~/pollusense/calibrate.py
import math

VC = 5.0
DIVIDER_TOTAL = 200_000

def rl_effective(rl_ohm, divider_total=DIVIDER_TOTAL):
    return rl_ohm * divider_total / (rl_ohm + divider_total)

def rs_from_mv(mv_at_ao, rl_eff_ohm, vc=VC):
    if mv_at_ao is None: return float("nan")
    v = mv_at_ao / 1000.0
    if v <= 0.01 or v >= vc: return float("nan")
    return rl_eff_ohm * (vc - v) / v

def mq135_trh_factor(t, rh):
    if t is None or rh is None or math.isnan(t) or math.isnan(rh): return 1.0
    return 0.00035 * t * t - 0.02718 * t + 1.39538 - (rh - 33.0) * 0.0018

def ppm_from_ratio(ratio, m, b):
    if ratio is None or not ratio > 0 or math.isnan(ratio): return float("nan")
    return 10 ** (m * math.log10(ratio) + b)

def no2_ugm3_from_ppm(ppm):
    return ppm * 1880.0 if not math.isnan(ppm) else float("nan")

def co_mgm3_from_ppm(ppm):
    return ppm * 1.145 if not math.isnan(ppm) else float("nan")
EOF
```

### 6.4 Dynamic Baseline Tool (`~/pollusense/r0.py`)

Create the `r0.py` script on the Pi:
```bash
cat <<'EOF' > ~/pollusense/r0.py
"""Compute R0 for MQ135 and MQ7 from raw_1min database over a time window.
Usage:
  # Compute from a specific UTC time window:
  ~/venv/bin/python ~/pollusense/r0.py "2026-11-18 10:00" "2026-11-18 11:00"

  # Or auto-compute from the last 1 hour of recorded data:
  ~/venv/bin/python ~/pollusense/r0.py --last1h
"""
import json, sqlite3, sys, statistics, os, time
from datetime import datetime, timezone
from calibrate import rl_effective, rs_from_mv, mq135_trh_factor

DB = os.path.expanduser("~/pollusense/data.db")
HW_PATH = os.path.expanduser("~/pollusense/hardware.json")

if not os.path.isfile(HW_PATH):
    print(f"Error: {HW_PATH} not found. Create hardware.json first.")
    sys.exit(1)

HW = json.load(open(HW_PATH))

RATIO_AIR_MQ135 = 3.6     # Rs/R0 in clean air (datasheet)
RATIO_AIR_MQ7   = 27.5    # Rs/R0 in clean air (datasheet)

def epoch(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())

def main(db, start, end):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
    ).fetchall()
    
    if not rows:
        print(f"No records found in database between epoch {start} and {end}.")
        print("Tip: Make sure the ESP32 has sent data during this time window.")
        return

    rl135 = rl_effective(HW["mq135_rl"])
    rl7   = rl_effective(HW["mq7_rl"])
    rs135, rs7, temps, rhs = [], [], [], []
    
    for (p,) in rows:
        d = json.loads(p)
        if d.get("uptime_s", 0) < 600 and len(rows) > 30:
            continue  # Discard first 10-min warm-up if plenty of data
        t, h = d.get("temp"), d.get("rh")
        r = rs_from_mv(d.get("mq135_mv"), rl135)
        if r == r and t is not None and h is not None:
            rs135.append(r / mq135_trh_factor(t, h))
            temps.append(t)
            rhs.append(h)
        r7 = rs_from_mv(d.get("mq7_mv"), rl7)
        if r7 == r7:
            rs7.append(r7)
            
    out = {
        "n_samples_mq135": len(rs135),
        "n_samples_mq7": len(rs7),
        "mq135_r0": round(statistics.median(rs135) / RATIO_AIR_MQ135, 1) if rs135 else None,
        "mq7_r0": round(statistics.median(rs7) / RATIO_AIR_MQ7, 1) if rs7 else None,
        "temp_median": statistics.median(temps) if temps else None,
        "rh_median": statistics.median(rhs) if rhs else None
    }
    
    print("\n========================================================")
    print("           CALCULATED SENSOR BASELINES (R0)")
    print("========================================================")
    print(json.dumps(out, indent=2))
    
    r0_path = os.path.expanduser("~/pollusense/r0.json")
    json.dump(out, open(r0_path, "w"), indent=2)
    print(f"\nSaved R0 baselines to {r0_path}")
    print("Tip: Update mq135_r0 and mq7_r0 in ~/pollusense/calibration.json with these values.\n")

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--last1h":
        now_ts = int(time.time())
        main(DB, now_ts - 3600, now_ts)
    elif len(sys.argv) >= 3:
        main(DB, epoch(sys.argv[1]), epoch(sys.argv[2]))
    else:
        # Default: auto-select last 1 hour of available data
        now_ts = int(time.time())
        main(DB, now_ts - 3600, now_ts)
EOF
```

Run this script to calculate clean air $R_0$ from the database over the **last 1 hour of data**:
```bash
~/venv/bin/python ~/pollusense/r0.py --last1h
```

Or calculate over a specific historical UTC hour (e.g., quiet early morning 00:00–01:00 UTC):
```bash
~/venv/bin/python ~/pollusense/r0.py "2026-11-18 00:00" "2026-11-18 01:00"
```

---

## 7. 15-Minute Aggregation: Rolling Mean & Direct CSV Storage

### 7.1 Aggregation Design (Phase 1)
* **Basic Rolling Mean**: Calculates the arithmetic mean ($\mu$) across all valid 1-minute measurements collected in each 15-minute window for $PM_{2.5}$, $PM_{10}$, temperature, humidity, $MQ135\text{ mV}$, and $MQ7\text{ mV}$.
* **Direct Continuous CSV Output**: Each 15-minute mean is immediately appended to `/home/edgepi2/pollusense/records_15min.csv`.
* **Outlier Rejection Deferred**: Advanced Hampel and outlier filtering are deferred to Phase 2, ensuring raw data continuity without dropped windows.

### 7.2 Aggregator Script (`~/pollusense/aggregate.py`)
```bash
cat <<'EOF' > ~/pollusense/aggregate.py
"""15-Minute Rolling Mean Aggregator with Direct CSV Storage.
Runs every 15 minutes (:01, :16, :31, :46) via systemd timer.
"""
import json, math, sqlite3, os, csv, time
from datetime import datetime, timezone, timedelta
from calibrate import (rl_effective, rs_from_mv, mq135_trh_factor,
                       ppm_from_ratio, no2_ugm3_from_ppm, co_mgm3_from_ppm)

DB = os.path.expanduser("~/pollusense/data.db")
CAL_PATH = os.path.expanduser("~/pollusense/calibration.json")
CSV_OUT = os.path.expanduser("~/pollusense/records_15min.csv")
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
EOF
```

### 7.3 Systemd Automation Timer
Set the aggregation worker to trigger at `:01, :16, :31, :46` minutes past every hour:
```bash
sudo tee /etc/systemd/system/ps-aggregate.service > /dev/null <<EOF
[Unit]
Description=PolluSense 15-min aggregation

[Service]
Type=oneshot
User=edgepi2
WorkingDirectory=/home/edgepi2/pollusense
ExecStart=/home/edgepi2/venv/bin/python /home/edgepi2/pollusense/aggregate.py
EOF

sudo tee /etc/systemd/system/ps-aggregate.timer > /dev/null <<EOF
[Unit]
Description=Run aggregation every 15 min

[Timer]
OnCalendar=*:01,16,31,46
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ps-aggregate.timer
systemctl list-timers | grep ps-aggregate
```

---

## 8. Live Diagnostics, Maintenance & CSV Export Tools

### 8.1 Live Calibrated Stream (`~/pollusense/live_calibrated.py`)

Create the `live_calibrated.py` dashboard script on the Pi:
```bash
cat <<'EOF' > ~/pollusense/live_calibrated.py
import json, time, os, math
from datetime import datetime, timezone, timedelta
import paho.mqtt.client as mqtt
from calibrate import (rl_effective, rs_from_mv, mq135_trh_factor,
                       ppm_from_ratio, no2_ugm3_from_ppm, co_mgm3_from_ppm)

CAL_PATH = os.path.expanduser("~/pollusense/calibration.json")
IST = timezone(timedelta(hours=5, minutes=30))

def calc_sub_index(c, b_low, b_high, i_low, i_high):
    return i_low + ((i_high - i_low) / (b_high - b_low)) * (c - b_low)

def sub_index_pm25(c):
    if c is None or math.isnan(c) or c < 0: return None
    if c <= 30:  return calc_sub_index(c, 0, 30, 0, 50)
    if c <= 60:  return calc_sub_index(c, 30, 60, 51, 100)
    if c <= 90:  return calc_sub_index(c, 60, 90, 101, 200)
    if c <= 120: return calc_sub_index(c, 90, 120, 201, 300)
    if c <= 250: return calc_sub_index(c, 120, 250, 301, 400)
    return calc_sub_index(min(c, 380), 250, 380, 401, 500)

def sub_index_pm10(c):
    if c is None or math.isnan(c) or c < 0: return None
    if c <= 50:  return calc_sub_index(c, 0, 50, 0, 50)
    if c <= 100: return calc_sub_index(c, 50, 100, 51, 100)
    if c <= 250: return calc_sub_index(c, 100, 250, 101, 200)
    if c <= 350: return calc_sub_index(c, 250, 350, 201, 300)
    if c <= 430: return calc_sub_index(c, 350, 430, 301, 400)
    return calc_sub_index(min(c, 510), 430, 510, 401, 500)

def sub_index_no2(c):
    if c is None or math.isnan(c) or c < 0: return None
    if c <= 40:  return calc_sub_index(c, 0, 40, 0, 50)
    if c <= 80:  return calc_sub_index(c, 40, 80, 51, 100)
    if c <= 180: return calc_sub_index(c, 80, 180, 101, 200)
    if c <= 280: return calc_sub_index(c, 180, 280, 201, 300)
    if c <= 400: return calc_sub_index(c, 280, 400, 301, 400)
    return calc_sub_index(min(c, 500), 400, 500, 401, 500)

def sub_index_co(c):
    if c is None or math.isnan(c) or c < 0: return None
    if c <= 1.0:  return calc_sub_index(c, 0.0, 1.0, 0, 50)
    if c <= 2.0:  return calc_sub_index(c, 1.0, 2.0, 51, 100)
    if c <= 10.0: return calc_sub_index(c, 2.0, 10.0, 101, 200)
    if c <= 17.0: return calc_sub_index(c, 10.0, 17.0, 201, 300)
    if c <= 34.0: return calc_sub_index(c, 17.0, 34.0, 301, 400)
    return calc_sub_index(min(c, 50.0), 34.0, 50.0, 401, 500)

def get_aqi_category(aqi):
    if aqi is None: return "Unknown"
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Satisfactory"
    if aqi <= 200: return "Moderate"
    if aqi <= 300: return "Poor"
    if aqi <= 400: return "Very Poor"
    return "Severe"

def on_connect(client, userdata, flags, reason_code, properties=None):
    print("\n========================================================")
    print("  POLLUSENSE LIVE CALIBRATED DASHBOARD")
    print("  Listening to raw ESP32 data on pollusense/+/raw...")
    print("========================================================\n")
    client.subscribe("pollusense/+/raw")

def on_message(client, userdata, msg):
    try:
        cal = json.load(open(CAL_PATH))
        d = json.loads(msg.payload.decode())
        
        rl135 = rl_effective(cal.get("mq135_rl", 1000))
        rl7   = rl_effective(cal.get("mq7_rl", 10000))
        
        t, h = d.get("temp"), d.get("rh")
        mv135, mv7 = d.get("mq135_mv"), d.get("mq7_mv")
        pm25, pm10 = d.get("pm25"), d.get("pm10")
        
        rs135 = rs_from_mv(mv135, rl135)
        rs7   = rs_from_mv(mv7, rl7)
        
        no2_ugm3 = float("nan")
        if not math.isnan(rs135) and t is not None and h is not None:
            ratio135 = rs135 / mq135_trh_factor(t, h) / cal["mq135_r0"]
            no2_ugm3 = no2_ugm3_from_ppm(ppm_from_ratio(ratio135, cal["no2_m"], cal["no2_b"]))
            
        co_mgm3 = float("nan")
        if not math.isnan(rs7):
            ratio7 = rs7 / cal["mq7_r0"]
            co_mgm3 = co_mgm3_from_ppm(ppm_from_ratio(ratio7, cal["co_m"], cal["co_b"]))
            
        s_pm25 = sub_index_pm25(pm25)
        s_pm10 = sub_index_pm10(pm10)
        s_no2  = sub_index_no2(no2_ugm3)
        s_co   = sub_index_co(co_mgm3)
        
        subs = [x for x in [s_pm25, s_pm10, s_no2, s_co] if x is not None]
        overall_aqi = round(max(subs)) if subs else None
        
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        print("============================================================")
        print(f" [{now_str}] Packet #{d.get('seq')} from Device '{d.get('device_id')}'")
        print("============================================================")
        print(f"  [+] PM 2.5 (CPCB)     : {pm25} µg/m³  (Sub-Index: {round(s_pm25) if s_pm25 else 'N/A'})")
        print(f"  [+] PM 10  (CPCB)     : {pm10} µg/m³  (Sub-Index: {round(s_pm10) if s_pm10 else 'N/A'})")
        print(f"  [+] Temperature       : {t} °C | Humidity: {h} %")
        print(f"  [+] MQ-135 Voltage    : {mv135} mV  ->  Rs: {round(rs135) if not math.isnan(rs135) else 'N/A'} Ω")
        print(f"  --> Calibrated NO2    : {round(no2_ugm3, 2) if not math.isnan(no2_ugm3) else 'N/A'} µg/m³  (Sub-Index: {round(s_no2) if s_no2 else 'N/A'})")
        print(f"  [+] MQ-7 Voltage      : {mv7} mV  ->  Rs: {round(rs7) if not math.isnan(rs7) else 'N/A'} Ω")
        print(f"  --> Calibrated CO     : {round(co_mgm3, 3) if not math.isnan(co_mgm3) else 'N/A'} mg/m³   (Sub-Index: {round(s_co) if s_co else 'N/A'})")
        print("------------------------------------------------------------")
        print(f"  [OVERALL CPCB AQI]    : {overall_aqi}  [Category: {get_aqi_category(overall_aqi)}]")
        print("============================================================\n")
    except Exception as e:
        print(f"[Live Monitor Error] {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_forever()
EOF

chmod +x ~/pollusense/live_calibrated.py
```

Run this script anytime to watch calibrated CPCB concentrations in real time:
```bash
~/venv/bin/python ~/pollusense/live_calibrated.py
```

### 8.2 Inspecting Continuous 15-Minute CSV
View the latest 10 aggregated 15-minute records directly from the CSV:
```bash
tail -n 10 ~/pollusense/records_15min.csv | column -s, -t
```

### 8.3 Essential Command Cheat Sheet

| Task | Command |
| :--- | :--- |
| **View Live MQTT Messages** | `mosquitto_sub -h localhost -t 'pollusense/#' -v` |
| **Check Ingest Status** | `systemctl status ps-ingest` |
| **Follow Ingest Live Logs** | `journalctl -u ps-ingest -f` |
| **Check Timers Status** | `systemctl list-timers \| grep ps-aggregate` |
| **View Latest 15-Min CSV Data**| `tail -n 10 ~/pollusense/records_15min.csv` |
| **Query Total Stored Messages** | `sqlite3 ~/pollusense/data.db "SELECT COUNT(*) FROM raw_1min;"` |
| **Inspect Latest 5 Raw Rows** | `sqlite3 ~/pollusense/data.db "SELECT datetime_ist, payload FROM raw_1min ORDER BY ts DESC LIMIT 5;"` |
| **Daily Packet Counts** | `sqlite3 ~/pollusense/data.db "SELECT date(datetime_ist), COUNT(*) FROM raw_1min GROUP BY date(datetime_ist);"` |
| **Check for Lost Packets** | `sqlite3 ~/pollusense/data.db "SELECT boot_id, MIN(seq), MAX(seq), COUNT(*), MAX(seq)-MIN(seq)+1-COUNT(*) AS lost FROM raw_1min GROUP BY boot_id;"` |
| **Restart Mosquitto Broker** | `sudo systemctl restart mosquitto` |
| **Test Port 1883 Binding** | `sudo ss -tulpn \| grep 1883` |
# PolluSense Raspberry Pi (RPi) Software & Services

This directory contains all the backend services, dynamic calibration logic, 15-minute rolling mean aggregator, Mosquitto broker configurations, and systemd automation timers for the Raspberry Pi.

---

## Directory Structure

```
rpi/
├── README.md                          # This manual
├── install.sh                         # One-click deployment script
├── config/
│   ├── hardware.json                  # Load resistor values (RL) for MQ-135 & MQ-7
│   ├── calibration.json               # Baseline R0, curve slopes, intercepts (b = -1.6500)
│   └── pollusense.conf                # Mosquitto listener configuration (Port 1883)
├── scripts/
│   ├── ingest.py                      # Background MQTT consumer saving raw packets to data.db
│   ├── calibrate.py                   # Math engine (divider compensation, Rs, T/RH, ppm -> CPCB)
│   ├── aggregate.py                   # 15-minute basic mean aggregator -> records_15min.csv
│   ├── r0.py                          # Clean-air R0 baseline calculation tool (--last1h)
│   ├── live_calibrated.py             # Live terminal monitoring dashboard (CPCB & AQI)
│   ├── export_csv.py                  # CSV exporter for raw or 15-minute records over time ranges
│   └── setup_dedicated_access.sh      # mDNS & static IP alias (192.168.1.50) setup script
└── systemd/
    ├── ps-ingest.service              # Ingest service unit
    ├── ps-aggregate.service           # 15-minute aggregation service unit
    ├── ps-aggregate.timer             # Aggregation timer (:01, :16, :31, :46 past every hour)
    └── permanent-ip-alias.service     # Permanent 192.168.1.50 network alias unit
```

---

## Automated Quick Deployment on Raspberry Pi

To deploy everything automatically on the Raspberry Pi:

```bash
# Clone or copy the repository onto the Raspberry Pi:
cd ~/pollusense-repo/rpi
chmod +x install.sh
./install.sh
```

---

## Manual Execution & Diagnostic Tools

All diagnostic and maintenance tools run using the virtual environment at `~/venv`:

### 1. Live Real-Time Dashboard
View incoming 1-minute measurements with on-the-fly calibration and CPCB AQI:
```bash
~/venv/bin/python ~/pollusense/live_calibrated.py
```

### 2. Recalculate Sensor Baselines ($R_0$)
Calculate $R_0$ from clean air over the last hour:
```bash
~/venv/bin/python ~/pollusense/r0.py --last1h
```

Or over a specific UTC time range:
```bash
~/venv/bin/python ~/pollusense/r0.py "2026-11-20 00:00" "2026-11-20 01:00"
```

### 3. Export Data for Research & Analysis
Export 15-minute records for a specific date range:
```bash
~/venv/bin/python ~/pollusense/export_csv.py --start "2026-11-20" --end "2026-11-27" --out weekly_report.csv
```

Export raw 1-minute data for a specific day:
```bash
~/venv/bin/python ~/pollusense/export_csv.py --table raw --start "2026-11-20 00:00:00" --end "2026-11-20 23:59:59" --out raw_day1.csv
```

---

## Reboot & Power Outage Behavior

All vital gateway functions are managed by systemd:
* **`ps-ingest.service`**: Automatically starts on boot. Recovers immediately if the Pi is restarted or power is restored.
* **`ps-aggregate.timer`**: Automatically active across reboots. Because `Persistent=true` is set, any 15-minute window missed during a power outage or reboot is triggered immediately upon startup.
* **`mosquitto.service`**: Starts automatically on boot.
* **`permanent-ip-alias.service`**: Binds `192.168.1.50` on boot for emergency or lab access.

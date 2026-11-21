// PolluSense Node Firmware - Arduino-ESP32 Core 3.x
// Pure Raw Telemetry Mode (No Heater Pin / No Cycle - Calibration & Mean Aggregation on Raspberry Pi)
#include <WiFi.h>
#include <PubSubClient.h>        // Library: "PubSubClient" by Nick O'Leary
#include <DHT.h>
#include <time.h>
#include <esp_system.h>

// ---------- edit these ----------
const char* WIFI_SSID = "NM_Lab";
const char* WIFI_PASS = "nm@123456";
const char* MQTT_HOST = "10.46.38.130";   // Raspberry Pi IP address
const int   MQTT_PORT = 1883;
const char* MQTT_USER = "pollusense";
const char* MQTT_PASS = "CHANGE_ME";      // Password (if enabled on broker)
const char* DEVICE_ID = "ps0123";
// --------------------------------

#define PMS_RX_PIN 16                     // ESP32 RX2 <- PMS7003 TX
#define PMS_TX_PIN 17                     // ESP32 TX2 -> PMS7003 RX
#define DHT_PIN 4
#define MQ135_PIN 34                      // ADC1
#define MQ7_PIN 35                        // ADC1 (Direct analog sensing, no heater control)
const float DIV_RATIO = 2.0f;             // 100k/100k divider (halves 0-5V to 0-2.5V)

DHT dht(DHT_PIN, DHT11);
WiFiClient net;
PubSubClient mqtt(net);
String topic;

uint32_t bootId, seq = 0;

// PM tracking (PM1.0 removed)
uint32_t pm25Sum = 0, pm10Sum = 0; 
uint16_t pmN = 0;

// Raw MQ Sensor Voltage Tracking (mV at module output)
float mq135Sum = 0; uint16_t mq135N = 0;
float mq7Sum   = 0; uint16_t mq7N   = 0;

uint32_t lastPublish = 0, lastSample = 0;
uint32_t lastWifiTry = 0, lastMqttTry = 0;

// Reads ADC in mV taking the 100k/100k divider into account
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

// ---------------- PMS7003 Frame Parser ----------------
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
    if (sum != (uint16_t)((buf[30] << 8) | buf[31])) continue; // Checksum fail
    
    // PM 1.0 ignored (bytes 10 & 11)
    pm25Sum += (buf[12] << 8) | buf[13]; // PM2.5 atmospheric (µg/m³)
    pm10Sum += (buf[14] << 8) | buf[15]; // PM10  atmospheric (µg/m³)
    pmN++;
  }
}

// ---------------- Connection Management ----------------
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

// ---------------- 1-Minute Raw Publish ----------------
void publishMinute() {
  float pm25 = pmN > 0 ? (pm25Sum / (float)pmN) : NAN;
  float pm10 = pmN > 0 ? (pm10Sum / (float)pmN) : NAN;
  float t = dht.readTemperature(), h = dht.readHumidity();
  float mq135 = mq135N ? (mq135Sum / mq135N) : NAN;
  float mq7   = mq7N   ? (mq7Sum / mq7N)     : NAN;
  time_t now = time(nullptr);
  
  // PURE RAW JSON payload for Raspberry Pi pipeline
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

  // MQTT Publish to Raspberry Pi
  bool published = false;
  if (mqtt.connected()) {
    published = mqtt.publish(topic.c_str(), js.c_str());
  }

  // Serial Monitor Summary
  Serial.println();
  Serial.println(F("================================================================"));
  Serial.print  (F("         POLLUSENSE RAW TELEMETRY REPORT  [Seq #"));
  Serial.print  (seq - 1);
  Serial.println(F("]"));
  Serial.println(F("================================================================"));
  Serial.print  (F("  [Raw] PM 2.5        : ")); Serial.print(num(pm25));  Serial.println(F(" µg/m³"));
  Serial.print  (F("  [Raw] PM 10         : ")); Serial.print(num(pm10));  Serial.println(F(" µg/m³"));
  Serial.print  (F("  [Raw] Temperature   : ")); Serial.print(num(t));     Serial.println(F(" °C"));
  Serial.print  (F("  [Raw] Humidity      : ")); Serial.print(num(h));     Serial.println(F(" %"));
  Serial.print  (F("  [Raw] MQ-135 Voltage: ")); Serial.print(num(mq135)); Serial.println(F(" mV"));
  Serial.print  (F("  [Raw] MQ-7 Voltage  : ")); Serial.print(num(mq7));   Serial.println(F(" mV"));
  Serial.print  (F("  [Raw] Valid Frames  : ")); Serial.println(pmN);
  Serial.println(F("----------------------------------------------------------------"));
  Serial.print  (F("  [MQTT Publish]      : "));
  Serial.println(published ? F("SUCCESS -> Sent to Pi") : F("FAILED / Disconnected"));
  Serial.print  (F("  [JSON Payload]      : ")); Serial.println(js);
  Serial.println(F("================================================================\n"));

  // Reset minute accumulators
  pm25Sum = pm10Sum = 0; 
  pmN = 0;
  mq135Sum = 0; mq135N = 0; 
  mq7Sum = 0;   mq7N = 0;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n========================================"));
  Serial.println(F("  PolluSense Node - Raw Telemetry Mode  "));
  Serial.println(F("  (No Heater Pin / Direct 5V Sensing)   "));
  Serial.println(F("========================================"));

  Serial2.begin(9600, SERIAL_8N1, PMS_RX_PIN, PMS_TX_PIN);
  dht.begin();
  
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);
  analogSetPinAttenuation(MQ7_PIN, ADC_11db);

  bootId = esp_random();

  // Pi / MQTT Network & NTP Setup
  topic = String("pollusense/") + DEVICE_ID + "/raw";
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // UTC timestamp synchronization
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);

  lastPublish = lastSample = millis();

  Serial.println(F("[System] Hardware & MQTT client ready.\n"));
}

void loop() {
  keepConnected();
  mqtt.loop();

  readPMS();

  // 5-second live reading print
  if (millis() - lastSample >= 5000) {
    lastSample = millis();
    
    float curMq135 = readMv(MQ135_PIN);
    mq135Sum += curMq135; 
    mq135N++;

    float curMq7 = readMv(MQ7_PIN);
    mq7Sum += curMq7; 
    mq7N++;

    Serial.print(F("[5s Live] "));
    Serial.print(F("Temp: "));  Serial.print(num(dht.readTemperature())); Serial.print(F(" °C | "));
    Serial.print(F("RH: "));    Serial.print(num(dht.readHumidity()));    Serial.print(F(" % | "));
    Serial.print(F("MQ135: ")); Serial.print(num(curMq135));              Serial.print(F(" mV | "));
    Serial.print(F("MQ7: "));   Serial.print(num(curMq7));                Serial.print(F(" mV | "));
    Serial.print(F("WiFi: "));  Serial.print(WiFi.status() == WL_CONNECTED ? F("Connected") : F("Connecting"));
    Serial.print(F(" | PMS: ")); Serial.println(pmN);
  }

  // 1-minute publish loop
  if (millis() - lastPublish >= 60000) {
    lastPublish += 60000;
    publishMinute();
  }
}

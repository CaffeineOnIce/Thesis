// PolluSense node firmware v1 -- Arduino-ESP32 core 3.x
// Libraries: PubSubClient (Nick O'Leary), DHT sensor library (Adafruit) + Adafruit Unified Sensor
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <time.h>
#include <esp_system.h>

// ---------- edit these ----------
const char* WIFI_SSID = "YOUR_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "192.168.1.50";   // the Pi's IP address
const int   MQTT_PORT = 1883;
const char* MQTT_USER = "pollusense";
const char* MQTT_PASS = "CHANGE_ME";
const char* DEVICE_ID = "ps01";
const bool  MQ7_CYCLE = true;             // false = constant 5 V fallback
// --------------------------------

#define PMS_RX_PIN 16       // ESP32 RX2 <- PMS7003 TX
#define PMS_TX_PIN 17       // ESP32 TX2 -> PMS7003 RX
#define DHT_PIN 4
#define MQ135_PIN 34        // ADC1
#define MQ7_PIN 35          // ADC1
#define MQ7_HEATER_PIN 25   // MOSFET gate
const float DIV_RATIO = 2.0f;                    // 100k/100k divider
const uint8_t DUTY_HIGH = 255, DUTY_LOW = 20;    // 20/255 = 7.8% ~ 1.4 V heating power

DHT dht(DHT_PIN, DHT11);
WiFiClient net;
PubSubClient mqtt(net);
String topic;

uint32_t bootId, seq = 0;
uint32_t pmSum[3] = {0, 0, 0}; uint16_t pmN = 0;
float mq135Sum = 0; uint16_t mq135N = 0;
float mq7MinSum = 0; uint16_t mq7MinN = 0;      // MQ7 results in this minute
bool lowPhase = false; uint32_t phaseStart = 0;
float mq7CycSum = 0; uint16_t mq7CycN = 0; uint32_t lastMq7Read = 0;
uint32_t lastPublish = 0, lastSample = 0, lastWifiTry = 0, lastMqttTry = 0;

float readMv(int pin) {                     // mean of 64 reads, in mV at the module output
  uint32_t s = 0;
  for (int i = 0; i < 64; i++) s += analogReadMilliVolts(pin);
  return (s / 64.0f) * DIV_RATIO;
}

String num(float v, int d = 1) { return isnan(v) ? String("null") : String(v, d); }

void readPMS() {                            // parse 32-byte frames: 0x42 0x4D ...
  static uint8_t buf[32]; static uint8_t idx = 0;
  while (Serial2.available()) {
    uint8_t c = Serial2.read();
    if (idx == 0 && c != 0x42) continue;
    if (idx == 1 && c != 0x4D) { idx = 0; continue; }
    buf[idx++] = c;
    if (idx < 32) continue;
    idx = 0;
    uint16_t sum = 0;
    for (int i = 0; i < 30; i++) sum += buf[i];
    if (sum != (uint16_t)((buf[30] << 8) | buf[31])) continue;   // bad checksum: drop frame
    pmSum[0] += (buf[10] << 8) | buf[11];   // PM1.0, atmospheric
    pmSum[1] += (buf[12] << 8) | buf[13];   // PM2.5, atmospheric
    pmSum[2] += (buf[14] << 8) | buf[15];   // PM10,  atmospheric
    pmN++;
  }
}

void heaterCycle() {                        // 60 s HIGH (5 V), 90 s LOW (~1.4 V)
  if (!MQ7_CYCLE) return;
  uint32_t el = millis() - phaseStart;
  if (!lowPhase && el >= 60000) {
    lowPhase = true; phaseStart = millis(); ledcWrite(MQ7_HEATER_PIN, DUTY_LOW);
    mq7CycSum = 0; mq7CycN = 0;
  } else if (lowPhase) {
    if (el >= 85000 && el < 90000 && millis() - lastMq7Read >= 250) {   // last 5 s of LOW
      mq7CycSum += readMv(MQ7_PIN); mq7CycN++; lastMq7Read = millis();
    }
    if (el >= 90000) {
      if (mq7CycN > 0) { mq7MinSum += mq7CycSum / mq7CycN; mq7MinN++; }
      lowPhase = false; phaseStart = millis(); ledcWrite(MQ7_HEATER_PIN, DUTY_HIGH);
    }
  }
}

void publishMinute() {
  float pm1 = NAN, pm25 = NAN, pm10 = NAN;
  if (pmN > 0) { pm1 = pmSum[0] / (float)pmN; pm25 = pmSum[1] / (float)pmN; pm10 = pmSum[2] / (float)pmN; }
  float t = dht.readTemperature(), h = dht.readHumidity();
  float mq135 = mq135N ? mq135Sum / mq135N : NAN;
  float mq7 = mq7MinN ? mq7MinSum / mq7MinN : NAN;
  time_t now = time(nullptr);
  String js = "{\"device_id\":\"" + String(DEVICE_ID) + "\"";
  js += ",\"boot_id\":" + String(bootId);
  js += ",\"seq\":" + String(seq++);
  js += ",\"ts\":" + (now > 1700000000 ? String((long)now) : String("null"));
  js += ",\"uptime_s\":" + String(millis() / 1000);
  js += ",\"rssi\":" + String(WiFi.RSSI());
  js += ",\"pm1\":" + num(pm1) + ",\"pm25\":" + num(pm25) + ",\"pm10\":" + num(pm10);
  js += ",\"pm_frames\":" + String(pmN);
  js += ",\"temp\":" + num(t) + ",\"rh\":" + num(h);
  js += ",\"mq135_mv\":" + num(mq135) + ",\"mq7_mv\":" + num(mq7);
  js += ",\"mq7_mode\":\"" + String(MQ7_CYCLE ? "cycle" : "constant") + "\"}";
  if (mqtt.connected()) mqtt.publish(topic.c_str(), js.c_str());
  Serial.println(js);
  pmSum[0] = pmSum[1] = pmSum[2] = 0; pmN = 0;
  mq135Sum = 0; mq135N = 0; mq7MinSum = 0; mq7MinN = 0;
}

void keepConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiTry > 10000) { WiFi.reconnect(); lastWifiTry = millis(); }
    return;
  }
  if (!mqtt.connected() && millis() - lastMqttTry > 5000) {
    lastMqttTry = millis();
    mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS);
  }
}

void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, PMS_RX_PIN, PMS_TX_PIN);
  dht.begin();
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);
  analogSetPinAttenuation(MQ7_PIN, ADC_11db);
  ledcAttach(MQ7_HEATER_PIN, 1000, 8);       // core 2.x: ledcSetup(0,1000,8); ledcAttachPin(MQ7_HEATER_PIN,0);
  ledcWrite(MQ7_HEATER_PIN, DUTY_HIGH);       // core 2.x: ledcWrite(0, DUTY_HIGH);
  bootId = esp_random();
  topic = String("pollusense/") + DEVICE_ID + "/raw";
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // UTC
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);                    // default 256 B is too small for our JSON
  phaseStart = lastPublish = lastSample = millis();
}

void loop() {
  keepConnected();
  mqtt.loop();
  readPMS();
  heaterCycle();
  if (millis() - lastSample >= 5000) {        // MQ135 every 5 s
    lastSample = millis();
    mq135Sum += readMv(MQ135_PIN); mq135N++;
    if (!MQ7_CYCLE) { mq7MinSum += readMv(MQ7_PIN); mq7MinN++; }
  }
  if (millis() - lastPublish >= 60000) { lastPublish += 60000; publishMinute(); }
}

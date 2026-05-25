#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"

// --- Intervals ---
const unsigned long READ_INTERVAL_MS = 30000;
const unsigned long MQTT_RETRY_MS    = 5000;

// --- Soil sensor ---
const int SOIL_PIN    = 32;
const int AIR_VALUE   = 2520;
const int WATER_VALUE = 550;

// --- Ring buffer ---
const int BUFFER_SIZE = 120;

struct Reading {
  float temperature;
  float pressure;
  int   soil_moisture;
  int   light;
  long  timestamp;
  char  message_id[40];
  bool  valid;
};

Reading ring_buffer[BUFFER_SIZE];
int buf_head      = 0;
int buf_count     = 0;
int overflow_count = 0;

Adafruit_BMP280 bmp;
WiFiClient      wifi_client;
PubSubClient    mqtt(wifi_client);

unsigned long last_read_ms  = 0;
unsigned long last_retry_ms = 0;
uint32_t      seq           = 0;

void generate_message_id(char* out, const char* device_id, long ts, uint32_t seq) {
  snprintf(out, 40, "%s-%ld-%04x", device_id, ts, seq & 0xFFFF);
}

long get_timestamp() {
  time_t now;
  time(&now);
  if (now < 1000000000L) return (long)(millis() / 1000);
  return (long)now;
}

void buffer_push(Reading& r) {
  if (buf_count == BUFFER_SIZE) {
    buf_head = (buf_head + 1) % BUFFER_SIZE;
    buf_count--;
    overflow_count++;
    Serial.println("[BUFFER] Overflow — oldest reading dropped.");
  }
  int idx = (buf_head + buf_count) % BUFFER_SIZE;
  ring_buffer[idx] = r;
  buf_count++;
}

Reading buffer_pop() {
  Reading r = ring_buffer[buf_head];
  ring_buffer[buf_head].valid = false;
  buf_head = (buf_head + 1) % BUFFER_SIZE;
  buf_count--;
  return r;
}

Reading read_sensors() {
  Reading r;
  r.valid       = true;
  r.temperature = bmp.readTemperature();
  r.pressure    = bmp.readPressure() / 100.0;
  r.light       = -1;

  int raw_soil    = analogRead(SOIL_PIN);
  r.soil_moisture = map(raw_soil, AIR_VALUE, WATER_VALUE, 0, 100);
  r.soil_moisture = constrain(r.soil_moisture, 0, 100);

  r.timestamp = get_timestamp();
  seq++;
  generate_message_id(r.message_id, DEVICE_ID, r.timestamp, seq);

  Serial.printf("[SENSOR] temp=%.1f°C  pressure=%.1fhPa  soil=%d%%\n",
                r.temperature, r.pressure, r.soil_moisture);
  return r;
}

bool publish_reading(const Reading& r) {
  StaticJsonDocument<256> doc;
  doc["schema_version"] = 1;
  doc["device_id"]      = DEVICE_ID;
  doc["message_id"]     = r.message_id;
  doc["temperature"]    = r.temperature;
  doc["humidity"]       = nullptr;
  doc["soil_moisture"]  = r.soil_moisture;
  doc["light"]          = r.light;
  doc["timestamp"]      = r.timestamp;
  if (overflow_count > 0) doc["overflow_count"] = overflow_count;

  char payload[256];
  serializeJson(doc, payload);

  bool ok = mqtt.publish(MQTT_TOPIC, payload, true);
  if (ok) Serial.printf("[MQTT] Published: %s\n", payload);
  else    Serial.println("[MQTT] Publish failed.");
  return ok;
}

void wifi_connect() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] Connected. IP: %s\n", WiFi.localIP().toString().c_str());
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    Serial.println("[NTP] Time sync requested.");
  } else {
    Serial.println("\n[WiFi] Failed — will retry.");
  }
}

bool mqtt_connect() {
  if (mqtt.connected()) return true;
  Serial.printf("[MQTT] Connecting to %s:%d ...\n", MQTT_HOST, MQTT_PORT);
  bool ok = mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD);
  if (ok) Serial.println("[MQTT] Connected.");
  else    Serial.printf("[MQTT] Failed, rc=%d\n", mqtt.state());
  return ok;
}

void flush_buffer() {
  if (buf_count == 0) return;
  Serial.printf("[BUFFER] Flushing %d buffered readings...\n", buf_count);
  while (buf_count > 0 && mqtt.connected()) {
    Reading r = buffer_pop();
    if (!publish_reading(r)) {
      buffer_push(r);
      break;
    }
    mqtt.loop();
    delay(100);
  }
  if (buf_count == 0) {
    overflow_count = 0;
    Serial.println("[BUFFER] Flush complete.");
  }
}

void setup() {
  delay(3000);
  Serial.begin(115200);
  Serial.println("\n=== Plant Monitor v1 ===");

  Wire.begin(21, 22);
  if (!bmp.begin(0x76)) {
    Serial.println("[ERROR] BMP280 not found!");
    while (1) delay(1000);
  }
  Serial.println("[OK] BMP280 ready.");

  pinMode(SOIL_PIN, INPUT);
  analogSetPinAttenuation((gpio_num_t)SOIL_PIN, ADC_11db);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(60);

  wifi_connect();
}

void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) wifi_connect();

  if (!mqtt.connected()) {
    if (now - last_retry_ms >= MQTT_RETRY_MS) {
      last_retry_ms = now;
      mqtt_connect();
      if (mqtt.connected()) flush_buffer();
    }
  }

  mqtt.loop();

  if (now - last_read_ms >= READ_INTERVAL_MS) {
    last_read_ms = now;
    Reading r = read_sensors();

    if (mqtt.connected()) {
      flush_buffer();
      if (!publish_reading(r)) buffer_push(r);
    } else {
      Serial.printf("[BUFFER] Offline. Buffering reading. Count: %d/%d\n",
                    buf_count + 1, BUFFER_SIZE);
      buffer_push(r);
    }
  }
}

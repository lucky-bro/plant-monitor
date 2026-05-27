#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"

// --- Intervals ---
const unsigned long READ_INTERVAL_MS    = 30000;   // sample sensors every 30s
const unsigned long HEARTBEAT_MS        = 180000;  // force publish at least every 3 min
const unsigned long MIN_PUBLISH_GAP_MS  = 60000;   // rate-limit delta publishes to ≥60s
const unsigned long MQTT_RETRY_MS       = 5000;

// --- Publish deltas (compare to last published value) ---
const float TEMP_DELTA = 0.5;
const float HUM_DELTA  = 2.0;
const int   SOIL_DELTA = 3;

// --- Soil sensor ---
const int SOIL_PIN    = 32;
const int AIR_VALUE   = 2520;
const int WATER_VALUE = 550;

// --- Ring buffer ---
const int BUFFER_SIZE = 120;

struct Reading {
  float temperature;
  float humidity;
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

Adafruit_BME280 bme;
WiFiClient      wifi_client;
PubSubClient    mqtt(wifi_client);

unsigned long last_read_ms       = 0;
unsigned long last_retry_ms      = 0;
unsigned long last_publish_ms    = 0;
uint32_t      seq                = 0;

float last_published_temp  = -999;
float last_published_hum   = -999;
int   last_published_soil  = -999;
bool  has_published        = false;

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
  r.temperature = bme.readTemperature();
  r.humidity    = roundf(bme.readHumidity() * 10) / 10;
  r.pressure    = bme.readPressure() / 100.0;
  r.light       = -1;

  int raw_soil    = analogRead(SOIL_PIN);
  r.soil_moisture = map(raw_soil, AIR_VALUE, WATER_VALUE, 0, 100);
  r.soil_moisture = constrain(r.soil_moisture, 0, 100);

  r.timestamp = get_timestamp();
  seq++;
  generate_message_id(r.message_id, DEVICE_ID, r.timestamp, seq);

  Serial.printf("[SENSOR] temp=%.1f°C  hum=%.1f%%  pressure=%.1fhPa  soil=%d%%\n",
                r.temperature, r.humidity, r.pressure, r.soil_moisture);
  return r;
}

bool should_publish(const Reading& r, unsigned long now) {
  // First reading ever — always publish.
  if (!has_published) return true;

  // Heartbeat — publish at least every HEARTBEAT_MS regardless of changes.
  if (now - last_publish_ms >= HEARTBEAT_MS) return true;

  // Don't republish too often — even on big changes, wait MIN_PUBLISH_GAP_MS.
  if (now - last_publish_ms < MIN_PUBLISH_GAP_MS) return false;

  // Compare against last PUBLISHED value (not last read) — prevents oscillation cascades.
  if (fabsf(r.temperature   - last_published_temp) >= TEMP_DELTA) return true;
  if (fabsf(r.humidity      - last_published_hum)  >= HUM_DELTA)  return true;
  if (abs  (r.soil_moisture - last_published_soil) >= SOIL_DELTA) return true;

  return false;
}

void mark_published(const Reading& r, unsigned long now) {
  last_published_temp = r.temperature;
  last_published_hum  = r.humidity;
  last_published_soil = r.soil_moisture;
  last_publish_ms     = now;
  has_published       = true;
}

bool publish_reading(const Reading& r) {
  StaticJsonDocument<256> doc;
  doc["schema_version"] = 1;
  doc["device_id"]      = DEVICE_ID;
  doc["message_id"]     = r.message_id;
  doc["temperature"]    = r.temperature;
  doc["humidity"]       = r.humidity;
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
  if (!bme.begin(0x76)) {
    Serial.println("[ERROR] BME280 not found!");
    while (1) delay(1000);
  }
  Serial.println("[OK] BME280 ready.");

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

    if (!should_publish(r, now)) {
      Serial.println("[PUBLISH] Skipped (no significant change, heartbeat not due).");
      return;
    }

    if (mqtt.connected()) {
      flush_buffer();
      if (publish_reading(r)) {
        mark_published(r, now);
      } else {
        buffer_push(r);
      }
    } else {
      Serial.printf("[BUFFER] Offline. Buffering reading. Count: %d/%d\n",
                    buf_count + 1, BUFFER_SIZE);
      buffer_push(r);
      // Mark as "published" for delta-tracking — buffered readings will be
      // flushed on reconnect, so no need to re-publish identical values.
      mark_published(r, now);
    }
  }
}

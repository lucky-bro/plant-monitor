#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "esp_sleep.h"
#include "config.h"

// ============================================================================
// Deep sleep schedule
// ============================================================================
const uint64_t SLEEP_DURATION_US = 5ULL * 60 * 1000000;  // 5 minutes
const int      WIFI_TIMEOUT_MS   = 15000;                // WiFi cold-start can take 10-12s
const int      MQTT_TIMEOUT_MS   = 5000;                 // give up on MQTT  after 5s
const int      NTP_WAIT_MS       = 10000;                // first boot can take ~5-8s; subsequent waks return instantly from RTC

// ============================================================================
// Pin map (ESP32-C3 Super Mini)
// ============================================================================
const int I2C_SDA  = 5;
const int I2C_SCL  = 6;
const int SOIL_PIN = 4;

// --- Soil sensor calibration (capacitive, 3.3V power) ---
const int AIR_VALUE         = 2925;
const int WATER_VALUE       = 750;
const int SOIL_SAMPLE_COUNT = 16;   // average N ADC reads to kill noise

// ============================================================================
// Ring buffer — survives deep sleep in RTC slow memory
// ============================================================================
const int BUFFER_SIZE = 60;  // 60 × 3 min = 3 hours of offline buffering

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

RTC_DATA_ATTR Reading  ring_buffer[BUFFER_SIZE];
RTC_DATA_ATTR int      buf_head        = 0;
RTC_DATA_ATTR int      buf_count       = 0;
RTC_DATA_ATTR int      overflow_count  = 0;
RTC_DATA_ATTR uint32_t seq             = 0;
RTC_DATA_ATTR uint32_t boot_count      = 0;

// ============================================================================
// Globals (re-initialized on every wake — these are RAM, not RTC)
// ============================================================================
Adafruit_BME280 bme;
BH1750          bh1750;
bool            bh1750_ok = false;
WiFiClient      wifi_client;
PubSubClient    mqtt(wifi_client);

// ============================================================================
// Helpers
// ============================================================================
void generate_message_id(char* out, const char* device_id, long ts, uint32_t s) {
  snprintf(out, 40, "%s-%ld-%04x", device_id, ts, s & 0xFFFF);
}

long get_timestamp() {
  time_t now;
  time(&now);
  if (now < 1000000000L) return (long)(millis() / 1000);  // NTP not synced — fallback
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

// ============================================================================
// Sensors
// ============================================================================
bool init_sensors() {
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!bme.begin(0x76)) {
    Serial.println("[ERROR] BME280 not found at 0x76!");
    return false;
  }
  Serial.println("[OK] BME280 ready.");

  if (bh1750.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
    bh1750_ok = true;
    Serial.println("[OK] BH1750 ready.");
  } else {
    Serial.println("[WARN] BH1750 not found — light will be -1.");
  }

  pinMode(SOIL_PIN, INPUT);
  analogSetPinAttenuation((gpio_num_t)SOIL_PIN, ADC_11db);
  return true;
}

int read_soil_avg() {
  long sum = 0;
  for (int i = 0; i < SOIL_SAMPLE_COUNT; i++) {
    sum += analogRead(SOIL_PIN);
    delay(2);
  }
  return (int)(sum / SOIL_SAMPLE_COUNT);
}

Reading read_sensors() {
  Reading r;
  r.valid       = true;
  r.temperature = bme.readTemperature();
  r.humidity    = roundf(bme.readHumidity() * 10) / 10;
  r.pressure    = bme.readPressure() / 100.0;

  if (bh1750_ok) {
    float lux = bh1750.readLightLevel();
    r.light = (lux >= 0) ? (int)lux : -1;
  } else {
    r.light = -1;
  }

  int raw_soil    = read_soil_avg();
  r.soil_moisture = map(raw_soil, AIR_VALUE, WATER_VALUE, 0, 100);
  r.soil_moisture = constrain(r.soil_moisture, 0, 100);

  r.timestamp = get_timestamp();
  seq++;
  generate_message_id(r.message_id, DEVICE_ID, r.timestamp, seq);

  Serial.printf("[SENSOR] temp=%.1f°C  hum=%.1f%%  pressure=%.1fhPa  soil=%d%%  light=%d\n",
                r.temperature, r.humidity, r.pressure, r.soil_moisture, r.light);
  return r;
}

// ============================================================================
// Network
// ============================================================================
bool wifi_connect() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  delay(50);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  for (int attempt = 1; attempt <= 2; attempt++) {
    Serial.printf("[WiFi] Attempt %d/2 → %s ", attempt, WIFI_SSID);
    WiFi.disconnect(true);
    delay(100);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) {
      delay(200);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\n[WiFi] Connected (attempt %d, %lums). IP=%s RSSI=%d dBm\n",
                    attempt, millis() - start,
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      return true;
    }
    Serial.printf("\n[WiFi] Attempt %d failed (status=%d).\n", attempt, WiFi.status());
  }
  return false;
}

void sync_ntp() {
  // Try Cloudflare (anycast, usually <30ms) + Google + pool as fallback.
  // Some routers/ISPs block outbound UDP 123 to less-known NTP hosts.
  configTime(0, 0, "time.cloudflare.com", "time.google.com", "pool.ntp.org");

  unsigned long start = millis();
  time_t now;
  while (millis() - start < NTP_WAIT_MS) {
    time(&now);
    if (now > 1000000000L) {
      Serial.printf("[NTP] Synced in %lums: %ld\n", millis() - start, (long)now);
      return;
    }
    delay(100);
  }
  time(&now);
  Serial.printf("[NTP] Timed out after %dms (time=%ld, using cached/fallback).\n",
                NTP_WAIT_MS, (long)now);
}

bool mqtt_connect() {
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  // Short keepalive: our active session is only a few seconds before deep sleep.
  // Broker will mark abandoned connections stale within ~22s instead of ~90s.
  mqtt.setKeepAlive(15);

  Serial.printf("[MQTT] Connecting to %s:%d ...\n", MQTT_HOST, MQTT_PORT);
  unsigned long start = millis();
  while (millis() - start < MQTT_TIMEOUT_MS) {
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD)) {
      Serial.println("[MQTT] Connected.");
      return true;
    }
    Serial.printf("[MQTT] Failed, rc=%d, retry...\n", mqtt.state());
    delay(500);
  }
  return false;
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

bool flush_buffer() {
  if (buf_count == 0) return true;
  Serial.printf("[BUFFER] Flushing %d buffered readings...\n", buf_count);
  while (buf_count > 0 && mqtt.connected()) {
    Reading r = buffer_pop();
    if (!publish_reading(r)) {
      buffer_push(r);
      return false;
    }
    mqtt.loop();
    delay(50);
  }
  if (buf_count == 0) {
    overflow_count = 0;
    Serial.println("[BUFFER] Flush complete.");
  }
  return true;
}

// ============================================================================
// Sleep
// ============================================================================
void go_to_sleep() {
  if (mqtt.connected()) {
    mqtt.disconnect();
    delay(100);  // let DISCONNECT packet and TCP FIN flush
  }
  WiFi.disconnect(true, true);  // disconnect + erase AP from RAM
  WiFi.mode(WIFI_OFF);
  delay(100);  // let WiFi stack settle

  Serial.printf("[SLEEP] Sleeping for %llu seconds...\n", SLEEP_DURATION_US / 1000000);
  Serial.flush();

  esp_sleep_enable_timer_wakeup(SLEEP_DURATION_US);
  esp_deep_sleep_start();
  // never returns
}

// ============================================================================
// Main — runs on every wake from deep sleep
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(200);  // let Serial settle

  boot_count++;
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  Serial.printf("\n=== Plant Monitor wake #%u (cause=%d, buf=%d, overflow=%d) ===\n",
                boot_count, cause, buf_count, overflow_count);

  if (!init_sensors()) {
    Serial.println("[FATAL] Sensor init failed, sleeping anyway.");
    go_to_sleep();
  }

  // Read FIRST so we have a reading even if WiFi fails
  Reading r = read_sensors();

  if (!wifi_connect()) {
    Serial.println("[BUFFER] No WiFi, buffering reading.");
    buffer_push(r);
    go_to_sleep();
  }

  sync_ntp();
  // Re-stamp timestamp in case NTP just arrived after our read
  r.timestamp = get_timestamp();
  generate_message_id(r.message_id, DEVICE_ID, r.timestamp, seq);

  if (!mqtt_connect()) {
    Serial.println("[BUFFER] No MQTT, buffering reading.");
    buffer_push(r);
    go_to_sleep();
  }

  // Flush any backlog first (preserves chronological order)
  flush_buffer();

  // Publish current reading
  if (!publish_reading(r)) {
    Serial.println("[BUFFER] Publish failed, buffering.");
    buffer_push(r);
  }

  // Give MQTT a moment to flush before disconnecting
  mqtt.loop();
  delay(200);

  go_to_sleep();
}

void loop() {
  // Never reached — all work happens in setup() then deep sleep.
}

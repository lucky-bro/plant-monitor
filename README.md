# 🌱 Plant Monitor

A production-style **AI + IoT** environmental monitoring system. Real hardware, real cloud, real failure handling — built end-to-end as a portfolio piece for an AI automation engineer role.

> **Live demo:** [plants.asytnyk.com](https://plants.asytnyk.com)

This project is deliberately over-engineered relative to keeping a plant alive. The plant is the pretext; the real subject is the full stack — battery-powered hardware, MQTT telemetry, idempotent ingestion, debounced alerting, LLM analysis, and a realtime dashboard — all running on a self-hosted VPS behind Traefik with HTTPS.

---

## ✨ Features

| | |
|---|---|
| 🔋 **Battery-powered ESP32** | Deep sleep between reads → **~50 days on a single 18650** |
| 📡 **MQTT telemetry** | Self-hosted Mosquitto, auth-enabled, idempotent ingestion |
| 🧠 **AI insights (Claude)** | Scheduled summaries of trends — *not* just raw alerts |
| 📊 **Realtime dashboard** | Next.js + SSE live updates, 24h/7d area charts |
| 🚨 **Telegram alerts** | Hysteresis + debounce + cooldown — no flapping, no spam |
| 🌐 **Public HTTPS deploy** | Docker + Traefik + Let's Encrypt on a single VPS |
| 🛡️ **Resilient** | Device buffers data on Wi-Fi loss, backend deduplicates, LLM failure gracefully degrades |

---

## 🏗️ Architecture

```
                ┌──────────────────┐
                │  ESP32-C3 +      │
                │  BME280, BH1750, │   reads sensors every 5 min,
                │  soil sensor     │   ring-buffers in RTC mem on outage
                └────────┬─────────┘
                         │ MQTT (auth, message_id)
                         ▼
                ┌──────────────────┐
                │   Mosquitto      │
                └────────┬─────────┘
                         │
                         ▼
        ┌─────────────────────────────────────┐
        │      FastAPI backend                │
        │  ┌─────────────────────────────┐    │
        │  │ idempotent ingestion        │    │
        │  │ alert engine (hyst+deb+cd)  │    │
        │  │ AI insights (Claude Haiku)  │    │
        │  │ SSE stream + REST API       │    │
        │  │ offline detection           │    │
        │  └─────────────────────────────┘    │
        └─┬───────────────┬───────────────────┘
          │               │
          ▼               ▼
    ┌──────────┐    ┌─────────────────┐    ┌──────────────────┐
    │PostgreSQL│    │ Next.js dashbrd │◀──▶│  Telegram bot    │
    └──────────┘    │  (SSE + charts) │    │  (whitelist)     │
                    └─────────────────┘    └──────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Firmware** | ESP32-C3, PlatformIO, C++, BME280, BH1750, capacitive soil sensor |
| **Transport** | MQTT (Mosquitto, auth) |
| **Backend** | Python 3.11, FastAPI, SQLAlchemy (async), asyncpg, paho-mqtt |
| **AI** | Anthropic Claude (Haiku 4.5) |
| **Bot** | python-telegram-bot |
| **Database** | PostgreSQL |
| **Frontend** | Next.js 16 (App Router, Turbopack), Tailwind v4, shadcn/ui, Recharts |
| **Infra** | Docker, Traefik, Let's Encrypt, VPS |

---

## 🔋 Power Story (the interesting part)

The ESP32-C3 firmware is **fully event-loop-free** — there's no `loop()`. Every cycle is:

```
wake from deep sleep
  → init sensors over I²C
  → read (16-sample ADC averaging for soil noise)
  → connect Wi-Fi (with retry + RSSI logging)
  → sync NTP (Cloudflare, ~4s on first boot)
  → MQTT connect, flush RTC ring buffer, publish current reading
  → clean disconnect + WiFi.mode(OFF)
  → esp_deep_sleep_start(5 min)
```

State that needs to survive sleep (`message_id` sequence, ring buffer with up to 5h of offline backlog, `overflow_count`) lives in `RTC_DATA_ATTR` slow memory.

Result: **~40 mAh/day** → ~50 days on a 3000 mAh 18650.

---

## 🧠 AI Insights

Twice in spec, four times in practice — Claude Haiku digests **24h of telemetry** into a compact JSON of avg/min/max + soil-moisture trend, then generates a 2–3 sentence actionable summary like:

> *"The soil moisture is trending wetter and is now consistently high at 77% average, having increased 9% over the last 24 hours. This suggests either recent overwatering or reduced evaporation, and you should hold off on watering until levels drop back to the 60-70% range to avoid root rot."*

Triggered every 6h **and** on any alert firing (cooldown-gated). Cached in PostgreSQL — the dashboard shows the cached version with a `stale` indicator if the LLM is down. Cost: ~$0.001 per insight = ~$0.12/month.

---

## 🚨 Alert Engine

The hard part of monitoring isn't detecting a threshold cross — it's not annoying the user.

| Mechanism | What it does |
|---|---|
| **Hysteresis** | Separate trigger / recovery thresholds (e.g. fires <40%, clears >45%) prevents flapping at the boundary |
| **Debounce** | Must hold for N consecutive readings before firing — single spurious spike doesn't alert |
| **Cooldown** | After firing, same alert type is suppressed for 30 min unless severity escalates |
| **Recovery msg** | Exactly one "recovered" notification when condition clears, then resets |
| **Smart online/offline** | "Back online" only fires if we actually sent an "offline" — prevents flapping on edge cases |

---

## 📦 Data Contract

```json
{
  "schema_version": 1,
  "device_id": "plant-01",
  "message_id": "plant-01-1780889065-0001",
  "temperature": 27.85,
  "humidity": 48.0,
  "soil_moisture": 78,
  "light": 320,
  "timestamp": 1780889065,
  "overflow_count": 0
}
```

- `schema_version` — forward compat
- `message_id` — `{device}-{unix_ts}-{seq}`, used for idempotent ingestion
- `overflow_count` — present only when the device dropped older buffered readings before reconnect

### Retention

| Tier | Granularity | Retention |
|---|---|---|
| Raw readings | per-message (~5 min) | 14 days |
| Hourly aggregates | 1 hour | 13 months |

7-day charts are served from aggregated rollups (SQL `AVG` per hour) to keep the wire small.

---

## 🌐 API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Telemetry counter + per-device online status |
| `GET` | `/devices` | All devices with online/offline + last-seen |
| `GET` | `/device/{id}/history?range=24h\|7d` | Time-series (raw or hourly-aggregated) |
| `GET` | `/alerts` | Currently firing alerts |
| `GET` | `/insights?device_id=...` | Latest cached AI insight |
| `POST` | `/insights/generate` | Manual insight regeneration (testing) |
| `GET` | `/events` | SSE stream — pushes every new telemetry packet to subscribed dashboards |

---

## 💬 Telegram Bot

Commands (chat ID whitelist enforced):

| Command | What it does |
|---|---|
| `/start` | Health check; replies with your chat ID if not in whitelist |
| `/status` | Current readings for the device |
| `/alerts` | List of active alerts |

Plus automatic notifications: alert firing, alert recovered, device offline, device back online — all anti-spam controlled.

---

## 📂 Project Structure

```
/firmware      — ESP32-C3, PlatformIO, deep-sleep architecture
/backend       — FastAPI + SQLAlchemy + MQTT consumer + Telegram bot + Claude integration
/frontend      — Next.js 16 dashboard (App Router, SSE, area charts)
/spec.md       — Original 30-day MVP spec
```

---

## 🚀 Setup

### 1. Firmware

```bash
cp firmware/src/config.example.h firmware/src/config.h
# Fill in Wi-Fi + MQTT credentials, then:
cd firmware && pio run --target upload
```

> **ESP32-C3 Super Mini note:** hold BOOT while plugging in USB to enter download mode (the auto-reset circuit on this board doesn't reliably trigger flash mode).

### 2. Backend

```bash
cp backend/.env.example backend/.env
# Fill in: DATABASE_URL, MQTT_*, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, ANTHROPIC_API_KEY
cd backend && docker compose up --build -d
```

### 3. Frontend

```bash
cd frontend && docker compose up --build -d
```

The frontend `docker-compose.yml` has Traefik labels for `plants.example.com` with `myresolver` (Let's Encrypt). Edit the host rule and you're public.

### 4. Mosquitto (if not already running)

```bash
docker run -d --name mosquitto -p 1883:1883 \
  -v mosquitto-data:/mosquitto/data \
  -v mosquitto-config:/mosquitto/config \
  eclipse-mosquitto

docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd esp32_plant
```

---

## 🎯 Governing Principle

> **Ship ugly. But ship real.**

Polish is negotiable. End-to-end correctness, predictable failure behavior, and a working public demo are not.

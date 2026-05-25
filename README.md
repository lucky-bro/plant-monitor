# Plant-monitor

A production-style AI + IoT environmental monitoring system.

This project is deliberately over-engineered relative to the task of keeping a plant alive. It's a training ground for the skills that matter for an AI automation engineering role: hardware, telemetry, realtime infrastructure, failure handling, AI analysis, dashboards, and notifications.

---

## What it does

- Reads air temperature, humidity, soil moisture, and light level from an ESP32 every 30 seconds
- Publishes telemetry over MQTT to a self-hosted broker
- Ingests, deduplicates, and persists readings to PostgreSQL
- Evaluates alert conditions with hysteresis, debounce, and cooldown (no flapping)
- Generates AI-powered insights on a scheduled cadence using an LLM
- Streams live updates to a Next.js dashboard via SSE
- Sends Telegram notifications with anti-spam control

---

## Architecture

```
[ESP32 + sensors]
       │ MQTT (every 30s, local ring buffer on outage)
       ▼
[Mosquitto — auth enabled]
       │
       ▼
[FastAPI backend]
  ├── telemetry ingestion (idempotent on message_id)
  ├── alert evaluation (hysteresis + debounce + cooldown)
  ├── AI insight generation (scheduled, cached, LLM-failure tolerant)
  ├── REST API + SSE stream
  └── /health endpoint
       │
  ┌────┴──────┐
  ▼           ▼
[PostgreSQL]  [Next.js dashboard]
       │
       ▼
[Telegram bot]
```

---

## Stack

| Layer | Technology |
|---|---|
| Firmware | ESP32, PlatformIO, C++ |
| Transport | MQTT, Mosquitto |
| Backend | Python, FastAPI, SQLAlchemy, asyncpg |
| Database | PostgreSQL |
| Frontend | Next.js, SSE |
| Infra | Docker, Traefik, VPS |

---

## Reliability highlights

This is the part that makes it production-style rather than a weekend prototype.

**Device-side resilience.** The ESP32 buffers up to 1 hour of readings in a local ring buffer on Wi-Fi or MQTT loss. On reconnect, buffered readings are flushed in order, each with its original timestamp and message_id. Oldest readings are dropped first on overflow.

**Idempotent ingestion.** The backend deduplicates on `message_id`, so device retries and buffer flushes never produce duplicate rows.

**Alert anti-spam.** Alerts use hysteresis (separate trigger and recovery thresholds), debounce (N consecutive readings before firing), and cooldown (suppressed for 30 min after send unless severity escalates). A resolved alert sends exactly one recovery message.

**Offline detection.** A device is marked offline if no telemetry arrives for 3× its expected interval. Exactly one notification on transition to offline; exactly one on recovery.

**LLM fault tolerance.** AI insight generation is scheduled and cached. If the LLM API is unavailable, the dashboard shows the last successful insight with a staleness indicator. AI failure never blocks telemetry, alerts, or the dashboard.

---

## Data contract

Every telemetry message includes a `schema_version` for forward compatibility and a unique `message_id` for idempotent ingestion.

```json
{
  "schema_version": 1,
  "device_id": "plant-01",
  "message_id": "plant-01-1755353535-7f3a",
  "temperature": 29.4,
  "humidity": 67,
  "soil_moisture": 41,
  "light": 820,
  "timestamp": 1755353535
}
```

---

## Data retention

| Tier | Granularity | Retention |
|---|---|---|
| Raw readings | per-message (~30s) | 14 days |
| Hourly aggregates | 1 hour | 13 months |

7-day charts are served from aggregates, not raw rows.

---

## API

| Method | Path | Description |
|---|---|---|
| POST | `/telemetry` | Ingest device telemetry (authenticated, idempotent) |
| GET | `/devices` | List devices and online/offline state |
| GET | `/device/:id/history` | Historical telemetry |
| GET | `/alerts` | Active alerts |
| GET | `/insights` | Latest cached AI insight |
| GET | `/events` | SSE stream of live updates |
| GET | `/health` | Ingest counters, error counts, last-seen per device |

---

## Project structure

```
/firmware      — ESP32, PlatformIO
/backend       — Python, FastAPI, MQTT consumer, SQLAlchemy
/frontend      — Next.js
/docs          — architecture, schemas, runbook
```

---

## Setup

### Firmware

1. Copy `firmware/src/config.example.h` to `firmware/src/config.h`
2. Fill in your Wi-Fi credentials, MQTT host, and credentials
3. Open the `firmware/` folder in PlatformIO and flash

### Backend

1. Copy `backend/.env.example` to `backend/.env` and fill in credentials
2. `docker compose up --build -d`

### Mosquitto

```bash
cd infra/mosquitto
docker compose up -d
docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd esp32_plant
```

---

## Governing principle

**Ship ugly. But ship real.**

Polish is negotiable. End-to-end correctness, predictable failure behavior, and a working public demo are not.
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from dotenv import load_dotenv

from database import engine, Base, AsyncSessionLocal
from models import TelemetryRaw, AlertState, DeviceState
import mqtt_client as mqtt_module
from alerts import evaluate_alerts
from offline import update_device_seen, offline_detection_loop
from telegram_bot import start_bot, stop_bot

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mqtt_client = None
main_loop   = None
sse_clients: list[asyncio.Queue] = []


async def broadcast(payload: dict):
    for queue in list(sse_clients):
        await queue.put(payload)


async def save_telemetry(payload: dict):
    try:
        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                text("SELECT id FROM telemetry_raw WHERE message_id = :mid"),
                {"mid": payload.get("message_id")}
            )
            if existing.fetchone():
                logger.info(f"[DB] Duplicate message_id={payload.get('message_id')}, skipping.")
                return

            session.add(TelemetryRaw(
                device_id      = payload.get("device_id"),
                message_id     = payload.get("message_id"),
                temperature    = payload.get("temperature"),
                humidity       = payload.get("humidity"),
                soil_moisture  = payload.get("soil_moisture"),
                light          = payload.get("light"),
                timestamp      = payload.get("timestamp"),
                overflow_count = payload.get("overflow_count"),
            ))
            await session.flush()

            device_id = payload.get("device_id")
            await update_device_seen(session, device_id)
            await evaluate_alerts(session, device_id, payload)

            await session.commit()
            logger.info(f"[DB] Saved: {payload.get('message_id')}")

        await broadcast(payload)
    except Exception as e:
        logger.error(f"[DB] Error saving telemetry: {e}")


def on_telemetry(payload: dict):
    if main_loop:
        asyncio.run_coroutine_threadsafe(save_telemetry(payload), main_loop)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client, main_loop

    main_loop = asyncio.get_event_loop()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[DB] Tables ready.")

    mqtt_module.on_telemetry_received = on_telemetry
    mqtt_client = mqtt_module.create_mqtt_client()
    mqtt_module.start_mqtt(mqtt_client)
    logger.info("[MQTT] Client started.")

    offline_task = asyncio.create_task(offline_detection_loop())
    await start_bot()

    yield

    await stop_bot()
    offline_task.cancel()
    if mqtt_client:
        mqtt_module.stop_mqtt(mqtt_client)
    logger.info("[MQTT] Client stopped.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    async with AsyncSessionLocal() as session:
        count_result = await session.execute(text("SELECT COUNT(*) FROM telemetry_raw"))
        telemetry_count = count_result.scalar()

        devices_result = await session.execute(select(DeviceState))
        devices = devices_result.scalars().all()

    return {
        "status": "ok",
        "telemetry_count": telemetry_count,
        "devices": [
            {
                "device_id":    d.device_id,
                "is_online":    d.is_online,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ],
    }


@app.get("/devices")
async def get_devices():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceState))
        devices = result.scalars().all()

    return {
        "devices": [
            {
                "device_id":    d.device_id,
                "is_online":    d.is_online,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ]
    }


@app.get("/alerts")
async def get_alerts():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlertState).where(AlertState.is_firing == True)
        )
        alerts = result.scalars().all()

    return {
        "alerts": [
            {
                "device_id":    a.device_id,
                "alert_type":   a.alert_type,
                "last_sent_at": a.last_sent_at.isoformat() if a.last_sent_at else None,
                "updated_at":   a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in alerts
        ]
    }


@app.get("/device/{device_id}/history")
async def get_history(device_id: str, range: str = Query("24h", pattern="^(24h|7d)$")):
    async with AsyncSessionLocal() as session:
        if range == "24h":
            result = await session.execute(
                text("""
                    SELECT timestamp, temperature, humidity, soil_moisture, light
                    FROM telemetry_raw
                    WHERE device_id = :device_id
                      AND received_at > NOW() - INTERVAL '24 hours'
                    ORDER BY timestamp ASC
                """),
                {"device_id": device_id},
            )
        else:
            result = await session.execute(
                text("""
                    SELECT
                        EXTRACT(EPOCH FROM date_trunc('hour', to_timestamp(timestamp)))::bigint AS timestamp,
                        ROUND(AVG(temperature)::numeric, 1)    AS temperature,
                        ROUND(AVG(humidity)::numeric, 1)       AS humidity,
                        ROUND(AVG(soil_moisture)::numeric)     AS soil_moisture,
                        ROUND(AVG(NULLIF(light, -1))::numeric) AS light
                    FROM telemetry_raw
                    WHERE device_id = :device_id
                      AND received_at > NOW() - INTERVAL '7 days'
                    GROUP BY date_trunc('hour', to_timestamp(timestamp))
                    ORDER BY timestamp ASC
                """),
                {"device_id": device_id},
            )
        rows = result.mappings().all()

    return {"device_id": device_id, "range": range, "data": [dict(r) for r in rows]}


@app.get("/events")
async def events():
    queue: asyncio.Queue = asyncio.Queue()
    sse_clients.append(queue)

    async def stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_clients.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/telemetry")
async def get_telemetry():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM telemetry_raw ORDER BY timestamp DESC LIMIT 50")
        )
        rows = result.mappings().all()
    return {"data": [dict(r) for r in rows]}

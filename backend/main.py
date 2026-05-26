import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select, text
from dotenv import load_dotenv

from database import engine, Base, AsyncSessionLocal
from models import TelemetryRaw, AlertState, DeviceState
import mqtt_client as mqtt_module
from alerts import evaluate_alerts
from offline import update_device_seen, offline_detection_loop

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mqtt_client = None
main_loop   = None


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

    yield

    offline_task.cancel()
    if mqtt_client:
        mqtt_module.stop_mqtt(mqtt_client)
    logger.info("[MQTT] Client stopped.")


app = FastAPI(lifespan=lifespan)


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
                "device_id":   d.device_id,
                "is_online":   d.is_online,
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
                "device_id":   d.device_id,
                "is_online":   d.is_online,
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
                "device_id":   a.device_id,
                "alert_type":  a.alert_type,
                "last_sent_at": a.last_sent_at.isoformat() if a.last_sent_at else None,
                "updated_at":  a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in alerts
        ]
    }


@app.get("/telemetry")
async def get_telemetry():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM telemetry_raw ORDER BY timestamp DESC LIMIT 50")
        )
        rows = result.mappings().all()
    return {"data": [dict(r) for r in rows]}

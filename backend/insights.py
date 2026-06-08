import asyncio
import logging
import os
from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

from database import AsyncSessionLocal
from models import Insight, DeviceState

load_dotenv()

logger = logging.getLogger(__name__)

INSIGHT_INTERVAL_HOURS = 6
LOOKBACK_HOURS         = 24
MIN_DATA_HOURS         = 1     # don't bother if we have less than this
LLM_MODEL              = "claude-haiku-4-5"
LLM_MAX_TOKENS         = 350

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_client = None


def _get_client():
    global _client
    if _client is None and ANTHROPIC_API_KEY:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


async def _gather_summary(session: AsyncSession, device_id: str) -> dict | None:
    """Pull aggregate stats for the device over LOOKBACK_HOURS. Returns None if no data."""
    result = await session.execute(
        text(f"""
            SELECT
                COUNT(*)                                AS n,
                MIN(received_at)                        AS first_seen,
                MAX(received_at)                        AS last_seen,
                ROUND(AVG(temperature)::numeric, 1)    AS temp_avg,
                ROUND(MIN(temperature)::numeric, 1)    AS temp_min,
                ROUND(MAX(temperature)::numeric, 1)    AS temp_max,
                ROUND(AVG(humidity)::numeric, 1)       AS hum_avg,
                ROUND(MIN(humidity)::numeric, 1)       AS hum_min,
                ROUND(MAX(humidity)::numeric, 1)       AS hum_max,
                ROUND(AVG(soil_moisture)::numeric)     AS soil_avg,
                ROUND(MIN(soil_moisture)::numeric)     AS soil_min,
                ROUND(MAX(soil_moisture)::numeric)     AS soil_max,
                ROUND(AVG(NULLIF(light, -1))::numeric) AS light_avg
            FROM telemetry_raw
            WHERE device_id = :device_id
              AND received_at > NOW() - INTERVAL '{LOOKBACK_HOURS} hours'
        """),
        {"device_id": device_id},
    )
    row = result.mappings().fetchone()
    if not row or not row["n"] or row["n"] < 3:
        return None

    # Soil trend: compare first vs last reading
    trend_result = await session.execute(
        text("""
            SELECT
                (SELECT soil_moisture FROM telemetry_raw
                 WHERE device_id = :device_id
                 ORDER BY received_at ASC  LIMIT 1) AS soil_start,
                (SELECT soil_moisture FROM telemetry_raw
                 WHERE device_id = :device_id
                 ORDER BY received_at DESC LIMIT 1) AS soil_end
        """),
        {"device_id": device_id},
    )
    trend = trend_result.mappings().fetchone()

    summary = dict(row)
    summary["soil_start"] = trend["soil_start"]
    summary["soil_end"]   = trend["soil_end"]
    return summary


def _build_prompt(device_id: str, s: dict) -> str:
    soil_trend = "stable"
    if s["soil_start"] is not None and s["soil_end"] is not None:
        delta = s["soil_end"] - s["soil_start"]
        if   delta < -5: soil_trend = f"drying ({delta}% over period)"
        elif delta >  5: soil_trend = f"wetter ({delta:+d}% over period)"

    light_line = f"Light: avg {s['light_avg']} lux" if s["light_avg"] is not None else "Light: no sensor data"

    return f"""You are analyzing environmental telemetry from a houseplant monitor ({device_id}).

Period: last {LOOKBACK_HOURS} hours, {s['n']} readings.

Temperature: avg {s['temp_avg']}°C (min {s['temp_min']}, max {s['temp_max']})
Humidity:    avg {s['hum_avg']}% (min {s['hum_min']}, max {s['hum_max']})
Soil moisture: avg {s['soil_avg']}% (min {s['soil_min']}, max {s['soil_max']}), trend: {soil_trend}
{light_line}

Provide ONE actionable insight in 2-3 short sentences. Focus on the most notable pattern.
If everything looks normal, briefly confirm. Do not list all numbers — synthesize.
Do not use markdown or formatting. Plain prose only."""


async def _call_llm(prompt: str) -> str | None:
    client = _get_client()
    if client is None:
        logger.warning("[INSIGHTS] ANTHROPIC_API_KEY not set, skipping.")
        return None

    try:
        resp = await client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(text_blocks).strip()
    except Exception as e:
        logger.error(f"[INSIGHTS] LLM call failed: {e}")
        return None


async def generate_insight(device_id: str, trigger: str = "scheduled") -> Insight | None:
    """Generate and store one insight. Returns the stored Insight or None on failure."""
    async with AsyncSessionLocal() as session:
        summary = await _gather_summary(session, device_id)
        if summary is None:
            logger.info(f"[INSIGHTS] Not enough data for {device_id}, skipping.")
            return None

        prompt = _build_prompt(device_id, summary)
        logger.info(f"[INSIGHTS] Generating insight for {device_id} (trigger={trigger})")

        text_out = await _call_llm(prompt)
        if not text_out:
            return None

        insight = Insight(
            device_id    = device_id,
            text         = text_out,
            trigger      = trigger,
            period_start = summary["first_seen"],
            period_end   = summary["last_seen"],
        )
        session.add(insight)
        await session.commit()
        await session.refresh(insight)
        logger.info(f"[INSIGHTS] Stored insight #{insight.id}: {text_out[:80]}...")
        return insight


async def get_latest_insight(device_id: str) -> Insight | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Insight)
            .where(Insight.device_id == device_id)
            .order_by(Insight.generated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def insights_loop():
    """Background task: generate insights for each known device every INSIGHT_INTERVAL_HOURS."""
    # Wait a bit on startup so DB and devices are ready
    await asyncio.sleep(30)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(DeviceState.device_id))
                device_ids = [row[0] for row in result.all()]

            for device_id in device_ids:
                await generate_insight(device_id, trigger="scheduled")
        except Exception as e:
            logger.error(f"[INSIGHTS] Loop iteration failed: {e}")

        await asyncio.sleep(INSIGHT_INTERVAL_HOURS * 3600)

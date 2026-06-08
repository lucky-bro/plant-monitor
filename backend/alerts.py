import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AlertState

logger = logging.getLogger(__name__)

DEBOUNCE_COUNT   = 2          # 2 consecutive readings (= ~10 min with 5-min deep sleep)
COOLDOWN_SECONDS = 30 * 60

ALERT_RULES = {
    "soil_moisture_low": {
        "field":            "soil_moisture",
        "trigger":          lambda v: v < 25,
        "recovery":         lambda v: v > 35,
        "message":          lambda device, v: f"{device}: soil moisture critical ({v}%).",
        "recovery_message": lambda device, v: f"{device}: soil moisture recovered ({v}%).",
    },
    "high_temperature": {
        "field":            "temperature",
        "trigger":          lambda v: v > 32,
        "recovery":         lambda v: v < 30,
        "message":          lambda device, v: f"{device}: temperature spike ({v:.1f}°C).",
        "recovery_message": lambda device, v: f"{device}: temperature normalized ({v:.1f}°C).",
    },
    "low_humidity": {
        "field":            "humidity",
        "trigger":          lambda v: v < 40,
        "recovery":         lambda v: v > 45,
        "message":          lambda device, v: f"{device}: humidity too low ({v:.1f}%).",
        "recovery_message": lambda device, v: f"{device}: humidity recovered ({v:.1f}%).",
    },
}

# Set from main.py once Telegram is wired up
notify_fn = None


async def _get_or_create(session: AsyncSession, device_id: str, alert_type: str) -> AlertState:
    result = await session.execute(
        select(AlertState).where(
            AlertState.device_id == device_id,
            AlertState.alert_type == alert_type,
        )
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = AlertState(device_id=device_id, alert_type=alert_type)
        session.add(state)
        await session.flush()
    return state


async def evaluate_alerts(session: AsyncSession, device_id: str, payload: dict):
    for alert_type, rule in ALERT_RULES.items():
        value = payload.get(rule["field"])
        if value is None or value < 0:
            continue

        state = await _get_or_create(session, device_id, alert_type)
        now = datetime.utcnow()

        if state.is_firing:
            if rule["recovery"](value):
                state.is_firing = False
                state.consecutive_count = 0
                state.updated_at = now
                msg = rule["recovery_message"](device_id, value)
                logger.info(f"[ALERT RECOVERED] {msg}")
                await _notify(msg)
        else:
            if rule["trigger"](value):
                state.consecutive_count += 1
                state.updated_at = now
                if state.consecutive_count >= DEBOUNCE_COUNT:
                    state.is_firing = True
                    state.consecutive_count = 0
                    in_cooldown = (
                        state.last_sent_at is not None
                        and (now - state.last_sent_at).total_seconds() < COOLDOWN_SECONDS
                    )
                    if not in_cooldown:
                        state.last_sent_at = now
                        msg = rule["message"](device_id, value)
                        logger.info(f"[ALERT] {msg}")
                        await _notify(msg)
                        # Kick off an AI insight regeneration in the background — gives the
                        # dashboard fresh context right when something interesting happened.
                        import asyncio
                        from insights import generate_insight
                        asyncio.create_task(generate_insight(device_id, trigger="alert"))
                    else:
                        logger.info(f"[ALERT] {alert_type} re-triggered but in cooldown, suppressed.")
            else:
                if state.consecutive_count != 0:
                    state.consecutive_count = 0
                    state.updated_at = now


async def _notify(message: str):
    from telegram_bot import send_notification
    await send_notification(message)

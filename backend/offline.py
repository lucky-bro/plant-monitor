import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DeviceState
from database import AsyncSessionLocal

logger = logging.getLogger(__name__)

OFFLINE_THRESHOLD_SECONDS = 18 * 60  # 3× wake interval + safety margin for occasional slow WiFi
CHECK_INTERVAL_SECONDS    = 60

# Set from main.py once Telegram is wired up
notify_fn = None


async def update_device_seen(session: AsyncSession, device_id: str):
    result = await session.execute(
        select(DeviceState).where(DeviceState.device_id == device_id)
    )
    state = result.scalar_one_or_none()
    now = datetime.utcnow()

    if state is None:
        session.add(DeviceState(device_id=device_id, is_online=True, last_seen_at=now))
    else:
        was_offline       = not state.is_online
        # Only notify recovery if we actually sent an offline notification.
        # Clearing offline_notified_at on recovery also re-arms the offline notifier.
        should_notify_up  = was_offline and state.offline_notified_at is not None
        state.is_online   = True
        state.last_seen_at = now
        state.updated_at  = now
        if should_notify_up:
            state.offline_notified_at = None
            msg = f"{device_id} is back online."
            logger.info(f"[DEVICE] {msg}")
            await _notify(msg)


async def _check_all_devices():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceState))
        devices = result.scalars().all()
        now = datetime.utcnow()

        for device in devices:
            if not device.is_online or device.last_seen_at is None:
                continue
            elapsed = (now - device.last_seen_at).total_seconds()
            if elapsed > OFFLINE_THRESHOLD_SECONDS:
                device.is_online = False
                device.updated_at = now
                already_notified = (
                    device.offline_notified_at is not None
                    and (now - device.offline_notified_at).total_seconds() < OFFLINE_THRESHOLD_SECONDS * 2
                )
                if not already_notified:
                    device.offline_notified_at = now
                    msg = f"{device.device_id} is offline."
                    logger.info(f"[DEVICE] {msg}")
                    await _notify(msg)

        await session.commit()


async def offline_detection_loop():
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            await _check_all_devices()
        except Exception as e:
            logger.error(f"[OFFLINE] Check failed: {e}")


async def _notify(message: str):
    from telegram_bot import send_notification
    await send_notification(message)

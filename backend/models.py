from sqlalchemy import Column, Integer, Float, String, BigInteger, DateTime, Boolean, UniqueConstraint, func
from database import Base


class TelemetryRaw(Base):
    __tablename__ = "telemetry_raw"

    id             = Column(Integer, primary_key=True, index=True)
    device_id      = Column(String, nullable=False, index=True)
    message_id     = Column(String, nullable=False, unique=True, index=True)
    temperature    = Column(Float)
    humidity       = Column(Float, nullable=True)
    soil_moisture  = Column(Integer)
    light          = Column(Integer, nullable=True)
    timestamp      = Column(BigInteger, nullable=False)
    received_at    = Column(DateTime, server_default=func.now())
    overflow_count = Column(Integer, nullable=True)


class AlertState(Base):
    __tablename__ = "alert_state"

    id                = Column(Integer, primary_key=True)
    device_id         = Column(String, nullable=False)
    alert_type        = Column(String, nullable=False)
    is_firing         = Column(Boolean, default=False, nullable=False)
    consecutive_count = Column(Integer, default=0, nullable=False)
    last_sent_at      = Column(DateTime, nullable=True)
    updated_at        = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "alert_type"),)


class DeviceState(Base):
    __tablename__ = "device_state"

    id                  = Column(Integer, primary_key=True)
    device_id           = Column(String, nullable=False, unique=True)
    is_online           = Column(Boolean, default=True, nullable=False)
    last_seen_at        = Column(DateTime, nullable=True)
    offline_notified_at = Column(DateTime, nullable=True)
    updated_at          = Column(DateTime, server_default=func.now())

from sqlalchemy import Column, Integer, Float, String, BigInteger, DateTime, func
from database import Base

class TelemetryRaw(Base):
    __tablename__ = "telemetry_raw"

    id            = Column(Integer, primary_key=True, index=True)
    device_id     = Column(String, nullable=False, index=True)
    message_id    = Column(String, nullable=False, unique=True, index=True)
    temperature   = Column(Float)
    humidity      = Column(Float, nullable=True)
    soil_moisture = Column(Integer)
    light         = Column(Integer, nullable=True)
    timestamp     = Column(BigInteger, nullable=False)
    received_at   = Column(DateTime, server_default=func.now())
    overflow_count = Column(Integer, nullable=True)

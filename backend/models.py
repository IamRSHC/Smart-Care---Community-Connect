"""
SmartCare - Data models

Resident        : one row per resident
Reading         : one row per sensor sample (vitals + motion)
Alert           : one row per detected anomaly
MedicationLog   : one row per medication schedule entry
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class Resident(Base):
    __tablename__ = "residents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    room_no = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)

    # caregiver-configurable safe ranges (defaults are generic elderly-care ranges)
    hr_min = Column(Float, default=50.0)
    hr_max = Column(Float, default=110.0)
    spo2_min = Column(Float, default=92.0)
    temp_min = Column(Float, default=35.5)
    temp_max = Column(Float, default=37.8)
    inactivity_minutes_threshold = Column(Integer, default=120)

    readings = relationship("Reading", back_populates="resident")
    alerts = relationship("Alert", back_populates="resident")
    medications = relationship("MedicationLog", back_populates="resident")


class Reading(Base):
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    heart_rate = Column(Float, nullable=True)       # bpm
    spo2 = Column(Float, nullable=True)              # %
    temperature = Column(Float, nullable=True)       # deg C
    accel_magnitude = Column(Float, nullable=True)   # g (from accelerometer)
    is_moving = Column(Boolean, default=False)       # derived from accel/gyro

    resident = relationship("Resident", back_populates="readings")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    alert_type = Column(String, nullable=False)   # e.g. "fall", "low_spo2", "high_hr", "inactivity"
    severity = Column(String, default="amber")    # "amber" or "red"
    message = Column(String, nullable=False)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    resident = relationship("Resident", back_populates="alerts")


class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    medicine_name = Column(String, nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    given = Column(Boolean, default=False)
    given_at = Column(DateTime, nullable=True)

    resident = relationship("Resident", back_populates="medications")

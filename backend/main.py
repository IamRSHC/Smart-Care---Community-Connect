"""
SmartCare backend - ingestion API, anomaly detection, alert broadcast,
caregiver dashboard API.

Run locally with:
    uvicorn main:app --reload --port 8000

On Render, the start command is:
    uvicorn main:app --host 0.0.0.0 --port $PORT
(see render.yaml)
"""
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import Base, engine, get_db
import models
from anomaly import evaluate_reading
from ai_summary import build_daily_summary

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SmartCare API")

# CORS_ORIGINS env var: comma-separated list, e.g.
#   CORS_ORIGINS=https://your-dashboard.vercel.app,http://localhost:5500
# Defaults to "*" (allow everything) so local dev and first deploy just work.
# Once you have your real Vercel URL, set CORS_ORIGINS on Render to lock
# this down - the PRD's privacy section expects access to be restricted,
# and a wildcard origin is fine for a demo but worth tightening for the report.
_cors_env = os.environ.get("CORS_ORIGINS", "*")
allow_origins = ["*"] if _cors_env.strip() == "*" else [o.strip() for o in _cors_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- WebSocket connection manager (pushes live alerts to dashboard) ----------

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive ping from client
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------- Schemas ----------

class SensorPayload(BaseModel):
    resident_id: int
    heart_rate: Optional[float] = None
    spo2: Optional[float] = None
    temperature: Optional[float] = None
    accel_magnitude: Optional[float] = None
    is_moving: Optional[bool] = False


class ResidentCreate(BaseModel):
    name: str
    room_no: Optional[str] = None
    age: Optional[int] = None


class AckPayload(BaseModel):
    staff_name: str


# ---------- Resident endpoints ----------

@app.post("/api/residents")
def create_resident(payload: ResidentCreate, db: Session = Depends(get_db)):
    resident = models.Resident(name=payload.name, room_no=payload.room_no, age=payload.age)
    db.add(resident)
    db.commit()
    db.refresh(resident)
    return resident


@app.get("/api/residents")
def list_residents(db: Session = Depends(get_db)):
    residents = db.query(models.Resident).all()
    result = []
    for r in residents:
        latest = (
            db.query(models.Reading)
            .filter(models.Reading.resident_id == r.id)
            .order_by(desc(models.Reading.timestamp))
            .first()
        )
        open_alerts = (
            db.query(models.Alert)
            .filter(models.Alert.resident_id == r.id, models.Alert.acknowledged == False)  # noqa: E712
            .count()
        )
        status = "green"
        if open_alerts:
            worst = (
                db.query(models.Alert)
                .filter(models.Alert.resident_id == r.id, models.Alert.acknowledged == False)  # noqa: E712
                .order_by(desc(models.Alert.severity))
                .first()
            )
            status = worst.severity if worst else "amber"
        result.append({
            "id": r.id,
            "name": r.name,
            "room_no": r.room_no,
            "status": status,
            "open_alerts": open_alerts,
            "latest_reading": {
                "heart_rate": latest.heart_rate if latest else None,
                "spo2": latest.spo2 if latest else None,
                "temperature": latest.temperature if latest else None,
                "timestamp": latest.timestamp.isoformat() if latest else None,
            } if latest else None,
        })
    return result


@app.get("/api/residents/{resident_id}/history")
def resident_history(resident_id: int, limit: int = 100, db: Session = Depends(get_db)):
    readings = (
        db.query(models.Reading)
        .filter(models.Reading.resident_id == resident_id)
        .order_by(desc(models.Reading.timestamp))
        .limit(limit)
        .all()
    )
    return list(reversed(readings))


# ---------- Ingestion endpoint (called by ESP32 firmware or simulator) ----------

@app.post("/api/ingest")
async def ingest_reading(payload: SensorPayload, db: Session = Depends(get_db)):
    resident = db.query(models.Resident).filter(models.Resident.id == payload.resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found")

    previous_reading = (
        db.query(models.Reading)
        .filter(models.Reading.resident_id == resident.id)
        .order_by(desc(models.Reading.timestamp))
        .first()
    )

    reading = models.Reading(
        resident_id=resident.id,
        heart_rate=payload.heart_rate,
        spo2=payload.spo2,
        temperature=payload.temperature,
        accel_magnitude=payload.accel_magnitude,
        is_moving=payload.is_moving,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    # find the last time this resident actually moved, for inactivity checks
    last_moving = (
        db.query(models.Reading)
        .filter(models.Reading.resident_id == resident.id, models.Reading.is_moving == True)  # noqa: E712
        .order_by(desc(models.Reading.timestamp))
        .first()
    )
    last_movement_time = last_moving.timestamp if last_moving else reading.timestamp

    new_alerts = evaluate_reading(resident, reading, previous_reading, last_movement_time)

    # Dedup: if this resident already has an open (unacknowledged) alert of
    # the same type, don't open a second one. Without this, a sustained
    # anomaly (e.g. a fall scenario sending several readings in a row, or a
    # resident staying below the SpO2 threshold for a few minutes) floods
    # the alert feed with dozens of near-identical entries instead of one
    # alert that stays open until staff acknowledge it.
    open_alert_types = {
        a.alert_type
        for a in db.query(models.Alert)
        .filter(models.Alert.resident_id == resident.id, models.Alert.acknowledged == False)  # noqa: E712
        .all()
    }
    new_alerts = [a for a in new_alerts if a.alert_type not in open_alert_types]

    for alert in new_alerts:
        db.add(alert)
    db.commit()

    for alert in new_alerts:
        db.refresh(alert)
        await manager.broadcast({
            "type": "alert",
            "id": alert.id,
            "resident_id": alert.resident_id,
            "resident_name": resident.name,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
        })

    return {"status": "ok", "alerts_raised": len(new_alerts)}


# ---------- Alerts ----------

@app.get("/api/alerts")
def list_alerts(unresolved_only: bool = True, db: Session = Depends(get_db)):
    query = db.query(models.Alert)
    if unresolved_only:
        query = query.filter(models.Alert.acknowledged == False)  # noqa: E712
    return query.order_by(desc(models.Alert.timestamp)).all()


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, payload: AckPayload, db: Session = Depends(get_db)):
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    alert.acknowledged_by = payload.staff_name
    alert.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"status": "acknowledged"}


# ---------- AI daily summary (Claude) ----------

@app.get("/api/residents/{resident_id}/daily-summary")
def daily_summary(resident_id: int, db: Session = Depends(get_db)):
    resident = db.query(models.Resident).filter(models.Resident.id == resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found")

    readings = (
        db.query(models.Reading)
        .filter(models.Reading.resident_id == resident_id)
        .order_by(desc(models.Reading.timestamp))
        .limit(200)
        .all()
    )
    if not readings:
        return {"summary": "No readings recorded yet today."}

    hrs = [r.heart_rate for r in readings if r.heart_rate is not None]
    spo2s = [r.spo2 for r in readings if r.spo2 is not None]
    temps = [r.temperature for r in readings if r.temperature is not None]
    active_count = sum(1 for r in readings if r.is_moving)

    stats = {
        "avg_hr": round(sum(hrs) / len(hrs), 1) if hrs else None,
        "min_spo2": min(spo2s) if spo2s else None,
        "avg_temp": round(sum(temps) / len(temps), 1) if temps else None,
        "active_readings": active_count,
        "total_readings": len(readings),
    }

    alerts = (
        db.query(models.Alert)
        .filter(models.Alert.resident_id == resident_id)
        .order_by(desc(models.Alert.timestamp))
        .limit(10)
        .all()
    )
    alert_list = [
        {"type": a.alert_type, "time": a.timestamp.strftime("%H:%M"), "resolved": a.acknowledged}
        for a in alerts
    ]

    meds = (
        db.query(models.MedicationLog)
        .filter(models.MedicationLog.resident_id == resident_id)
        .order_by(desc(models.MedicationLog.scheduled_time))
        .limit(10)
        .all()
    )
    med_list = [
        {"name": m.medicine_name, "time": m.scheduled_time.strftime("%H:%M"), "given": m.given}
        for m in meds
    ]

    summary_text = build_daily_summary(resident.name, stats, alert_list, med_list)
    return {"summary": summary_text, "stats": stats}


@app.get("/")
def root():
    return {"service": "SmartCare API", "status": "running"}

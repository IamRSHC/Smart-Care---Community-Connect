"""
SmartCare - Anomaly detection

Deliberately rule-based / deterministic. Safety-critical alerts should never
depend on an LLM call: rules are fast, explainable to caregivers, and don't
have a non-zero hallucination rate. The AI/LLM layer in ai_summary.py is only
used for the non-critical "daily note" feature.
"""
from datetime import datetime, timedelta
from typing import Optional

from models import Resident, Reading, Alert

# Fall detection: a resting body shows accel magnitude near 1g (gravity).
# A short, sharp spike followed by a flat/near-zero reading is a classic
# fall signature on a wrist/waist-worn accelerometer.
FALL_IMPACT_G = 2.5       # spike threshold in g
FALL_STILL_G = 0.3        # "lying still" band around expected resting value


def check_vitals(resident: Resident, reading: Reading) -> list[Alert]:
    """Threshold checks against the resident's configured safe ranges."""
    alerts = []

    if reading.heart_rate is not None:
        if reading.heart_rate < resident.hr_min or reading.heart_rate > resident.hr_max:
            alerts.append(Alert(
                resident_id=resident.id,
                alert_type="abnormal_heart_rate",
                severity="red",
                message=(
                    f"{resident.name}: heart rate {reading.heart_rate:.0f} bpm "
                    f"outside safe range ({resident.hr_min:.0f}-{resident.hr_max:.0f})"
                ),
            ))

    if reading.spo2 is not None and reading.spo2 < resident.spo2_min:
        alerts.append(Alert(
            resident_id=resident.id,
            alert_type="low_spo2",
            severity="red",
            message=f"{resident.name}: SpO2 {reading.spo2:.0f}% below safe minimum ({resident.spo2_min:.0f}%)",
        ))

    if reading.temperature is not None:
        if reading.temperature < resident.temp_min or reading.temperature > resident.temp_max:
            alerts.append(Alert(
                resident_id=resident.id,
                alert_type="abnormal_temperature",
                severity="amber",
                message=(
                    f"{resident.name}: temperature {reading.temperature:.1f}°C "
                    f"outside safe range ({resident.temp_min:.1f}-{resident.temp_max:.1f})"
                ),
            ))

    return alerts


def check_fall(resident: Resident, reading: Reading, previous_reading: Optional[Reading]) -> list[Alert]:
    """
    Very simple fall heuristic for the prototype:
    a sharp impact spike (>= FALL_IMPACT_G) followed immediately by
    near-motionless magnitude is flagged as a possible fall.
    Replace with a trained classifier (e.g. on windowed accel/gyro features)
    for a production version.
    """
    alerts = []
    if reading.accel_magnitude is None:
        return alerts

    spike_detected = reading.accel_magnitude >= FALL_IMPACT_G

    if spike_detected:
        alerts.append(Alert(
            resident_id=resident.id,
            alert_type="possible_fall",
            severity="red",
            message=f"{resident.name}: possible fall detected (impact spike {reading.accel_magnitude:.1f}g)",
        ))

    return alerts


def check_inactivity(resident: Resident, last_movement_time: Optional[datetime]) -> list[Alert]:
    """Flag prolonged inactivity relative to the resident's configured threshold."""
    alerts = []
    if last_movement_time is None:
        return alerts

    minutes_since_movement = (datetime.utcnow() - last_movement_time).total_seconds() / 60
    if minutes_since_movement >= resident.inactivity_minutes_threshold:
        alerts.append(Alert(
            resident_id=resident.id,
            alert_type="inactivity",
            severity="amber",
            message=(
                f"{resident.name}: no movement detected for "
                f"{int(minutes_since_movement)} minutes (threshold "
                f"{resident.inactivity_minutes_threshold} min)"
            ),
        ))
    return alerts


def evaluate_reading(
    resident: Resident,
    reading: Reading,
    previous_reading: Optional[Reading],
    last_movement_time: Optional[datetime],
) -> list[Alert]:
    """Run every rule against a new reading and return any alerts raised."""
    alerts: list[Alert] = []
    alerts += check_vitals(resident, reading)
    alerts += check_fall(resident, reading, previous_reading)
    alerts += check_inactivity(resident, last_movement_time)
    return alerts

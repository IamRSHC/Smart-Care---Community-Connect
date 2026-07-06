"""
SmartCare - Sensor simulator

Generates realistic vitals + motion data for one or more residents and posts
it to the backend /api/ingest endpoint, so the dashboard and alerting can be
demoed and tested before/without the ESP32 hardware being ready.

Usage:
    python simulate_sensors.py --resident-id 1 --scenario normal
    python simulate_sensors.py --resident-id 1 --scenario fall
    python simulate_sensors.py --resident-id 1 --scenario low_spo2
"""
import argparse
import random
import time
import requests

API_URL = "http://localhost:8000/api/ingest"


def normal_reading():
    return {
        "heart_rate": round(random.uniform(65, 85), 1),
        "spo2": round(random.uniform(95, 99), 1),
        "temperature": round(random.uniform(36.2, 37.1), 1),
        "accel_magnitude": round(random.uniform(0.9, 1.1), 2),
        "is_moving": random.random() < 0.5,
    }


def fall_reading():
    return {
        "heart_rate": round(random.uniform(90, 110), 1),  # spike from shock
        "spo2": round(random.uniform(93, 97), 1),
        "temperature": round(random.uniform(36.2, 37.1), 1),
        "accel_magnitude": round(random.uniform(2.6, 4.0), 2),  # impact spike
        "is_moving": False,
    }


def low_spo2_reading():
    return {
        "heart_rate": round(random.uniform(80, 100), 1),
        "spo2": round(random.uniform(85, 91), 1),
        "temperature": round(random.uniform(36.2, 37.4), 1),
        "accel_magnitude": round(random.uniform(0.9, 1.1), 2),
        "is_moving": False,
    }


def inactivity_reading():
    return {
        "heart_rate": round(random.uniform(60, 70), 1),
        "spo2": round(random.uniform(95, 98), 1),
        "temperature": round(random.uniform(36.0, 36.8), 1),
        "accel_magnitude": round(random.uniform(0.98, 1.02), 2),
        "is_moving": False,
    }


SCENARIOS = {
    "normal": normal_reading,
    "fall": fall_reading,
    "low_spo2": low_spo2_reading,
    "inactivity": inactivity_reading,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resident-id", type=int, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS.keys(), default="normal")
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between readings")
    parser.add_argument("--count", type=int, default=20, help="number of readings to send")
    args = parser.parse_args()

    generator = SCENARIOS[args.scenario]

    for i in range(args.count):
        reading = generator()
        reading["resident_id"] = args.resident_id
        try:
            resp = requests.post(API_URL, json=reading, timeout=5)
            print(f"[{i+1}/{args.count}] sent {args.scenario} reading -> {resp.status_code} {resp.json()}")
        except requests.RequestException as e:
            print(f"Error posting reading: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

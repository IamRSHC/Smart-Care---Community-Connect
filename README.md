# SmartCare — AI-Assisted Health & Activity Monitoring for Elderly Residents

Community Connect (21GNP301L) prototype, built for and piloted at **Sree Sai Saran Trust**, Srirangam, Trichy.

## Architecture

```
┌─────────────────────┐        Wi-Fi / HTTP POST        ┌──────────────────────────────┐
│  ESP32 Sensor Node   │ ───────────────────────────────▶│   FastAPI Backend             │
│  (firmware/)         │        /api/ingest               │   (backend/main.py)           │
│  - MAX30105 (HR/SpO2)│                                   │                                │
│  - DS18B20 (temp)    │        or, for demos:            │   ┌──────────────────────────┐ │
│  - MPU6050 (motion)  │◀── simulator/simulate_sensors.py │   │ anomaly.py               │ │
└─────────────────────┘                                   │   │ rule-based detection:    │ │
                                                            │   │ - vitals out of range    │ │
                                                            │   │ - fall (accel spike)     │ │
                                                            │   │ - inactivity timeout     │ │
                                                            │   └──────────────────────────┘ │
                                                            │   ┌──────────────────────────┐ │
                                                            │   │ ai_summary.py            │ │
                                                            │   │ Claude API call — daily  │ │
                                                            │   │ plain-language note only │ │
                                                            │   │ (never used for alerts)  │ │
                                                            │   └──────────────────────────┘ │
                                                            │   SQLite DB (models.py)        │
                                                            └───────────────┬──────────────┘
                                                                            │
                                                       REST (poll)  +  WebSocket (push alerts)
                                                                            │
                                                            ┌───────────────▼──────────────┐
                                                            │  Caregiver Dashboard (web)     │
                                                            │  dashboard/index.html          │
                                                            │  - resident status cards       │
                                                            │  - live alert feed             │
                                                            │  - acknowledge / resolve       │
                                                            └───────────────────────────────┘
```

**Design principle:** anomaly detection (falls, abnormal vitals, inactivity) is 100% deterministic,
rule-based logic in `anomaly.py`. The Claude/LLM call in `ai_summary.py` is used *only* for the
optional "daily caregiver note" feature — safety-critical alerting never depends on a model call.

## Project layout

```
smartcare/
├── backend/
│   ├── main.py          FastAPI app: ingestion, alerts, WebSocket, daily summary
│   ├── models.py        SQLAlchemy models (Resident, Reading, Alert, MedicationLog)
│   ├── anomaly.py       Rule-based fall / vitals / inactivity detection
│   ├── ai_summary.py    Claude API call for the daily plain-language note
│   ├── database.py      SQLite session setup
│   └── requirements.txt
├── simulator/
│   └── simulate_sensors.py   Generates fake sensor data for demos (normal/fall/low_spo2/inactivity)
├── dashboard/
│   └── index.html        Caregiver dashboard (vanilla HTML/CSS/JS, no build step)
└── firmware/
    └── smartcare_node/
        └── smartcare_node.ino   ESP32 Arduino sketch for the real sensor node
```

## Running the prototype (no hardware needed)

1. **Install backend dependencies**
   ```bash
   cd backend
   python -m venv venv && source venv/bin/activate   # (or venv\Scripts\activate on Windows)
   pip install -r requirements.txt
   export ANTHROPIC_API_KEY=your_key_here   # only needed for the /daily-summary endpoint
   uvicorn main:app --reload --port 8000
   ```

2. **Register a resident** (one-time, e.g. via curl or any REST client)
   ```bash
   curl -X POST http://localhost:8000/api/residents \
     -H "Content-Type: application/json" \
     -d '{"name": "Kamala Devi", "room_no": "A-3", "age": 78}'
   ```

3. **Open the dashboard**
   Just open `dashboard/index.html` in a browser (double-click it, or serve it with
   `python -m http.server` from the `dashboard/` folder). It talks to `localhost:8000`.

4. **Feed it demo data**
   ```bash
   cd simulator
   pip install requests
   python simulate_sensors.py --resident-id 1 --scenario normal
   python simulate_sensors.py --resident-id 1 --scenario fall        # triggers a red alert
   python simulate_sensors.py --resident-id 1 --scenario low_spo2    # triggers a red alert
   python simulate_sensors.py --resident-id 1 --scenario inactivity  # triggers an amber alert (after threshold)
   ```

5. Watch alerts appear live on the dashboard and try **Acknowledge**.

## Moving to real hardware

Flash `firmware/smartcare_node/smartcare_node.ino` to an ESP32 with a MAX30105, DS18B20, and
MPU6050 wired up, fill in your Wi-Fi credentials and backend IP at the top of the file, and it will
POST real readings to the same `/api/ingest` endpoint the simulator uses — no backend changes needed.
The heart-rate/SpO2 extraction is left as a placeholder; swap in SparkFun's
`maxim_heart_rate_and_oxygen_saturation()` routine from the MAX3010x library examples for real values.

## Deploying (Render backend + Vercel dashboard)

The backend is a stateful FastAPI app (SQLite/Postgres + a WebSocket connection
manager) - that shape doesn't fit Vercel's serverless functions (ephemeral
filesystem, no persistent WebSocket process). Split it instead:

**Backend -> Render**
1. Push this repo to GitHub.
2. In Render: New -> Blueprint -> point at the repo. `render.yaml` at the
   repo root provisions the web service and a free Postgres DB together and
   wires `DATABASE_URL` automatically.
3. In the Render dashboard, set `ANTHROPIC_API_KEY` under the service's
   Environment tab (only needed for the `/daily-summary` endpoint).
4. Once live, note the service URL, e.g. `https://smartcare-backend.onrender.com`.

**Dashboard -> Vercel**
1. In Vercel: New Project -> import the same repo -> set **Root Directory**
   to `dashboard`. No build command needed (it's a single static HTML file).
2. Before or after deploying, edit `dashboard/index.html`: set `BACKEND_HOST`
   to your Render host (no `https://`, no trailing slash), e.g.
   `"smartcare-backend.onrender.com"`. Redeploy on Vercel after editing.
3. Optional but recommended: back in Render, set `CORS_ORIGINS` to your
   exact Vercel URL instead of leaving it as `*`.

**Known limitation:** Render's free tier spins the service down after ~15 min
of inactivity; the next request wakes it up with a 30-60s delay. Hit the
backend URL once a minute or so before a live demo so it's warm.

## Notes for the Community Connect report

- Anomaly thresholds per resident (`hr_min/max`, `spo2_min`, `temp_min/max`,
  `inactivity_minutes_threshold`) are configurable per row in `models.Resident`, so caregivers can
  tune them per resident during the pilot week rather than using one fixed rule for everyone.
- All resident data should only be collected after informed consent from the resident/guardian and
  the Trust, per the PRD's privacy section.
- This is a proof-of-concept: production use would need proper encryption at rest, authentication on
  the API, and a trained (not heuristic) fall-detection classifier.

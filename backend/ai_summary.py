"""
SmartCare - AI-assisted daily caregiver notes

This is the ONLY place an LLM is used in the whole system. It turns a
resident's structured logs (vitals stats + alerts + medication compliance)
into a short, plain-language note a caregiver can read in five seconds.

Deliberately NOT used for real-time alerting - that stays in anomaly.py
as deterministic rule checks, so a model hiccup can never delay a
safety-critical alert.

Requires an ANTHROPIC_API_KEY environment variable
(see: https://docs.claude.com for how API keys and models are managed).
"""
import os
from datetime import datetime
from anthropic import Anthropic

MODEL_NAME = "claude-sonnet-4-6"  # swap for the latest available model as needed

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it in your shell or .env file."
            )
        _client = Anthropic(api_key=api_key)
    return _client


def build_daily_summary(resident_name: str, stats: dict, alerts: list[dict], meds: list[dict]) -> str:
    """
    stats  = {"avg_hr": 78, "min_spo2": 94, "avg_temp": 36.7, "active_minutes": 210}
    alerts = [{"type": "possible_fall", "time": "14:32", "resolved": True}, ...]
    meds   = [{"name": "Metformin", "time": "08:00", "given": True}, ...]
    """
    prompt = f"""You are helping old-age-home staff quickly understand a resident's day.
Resident: {resident_name}
Date: {datetime.utcnow().strftime('%Y-%m-%d')}

Vitals summary: {stats}
Alerts raised today: {alerts}
Medication log: {meds}

Write a short caregiver-facing note (3-5 sentences, plain language, no
medical jargon, no diagnosis). Mention anything that needs follow-up.
If everything was normal, say so briefly and reassuringly."""

    client = _get_client()
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")

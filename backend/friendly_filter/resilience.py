"""Operator-visible health policy layered over replay counters."""

from enum import StrEnum


class HealthState(StrEnum):
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    BLACKOUT = "BLACKOUT"


def summarize_health(health: dict[str, dict], stale_tracks: int, blocked_assignments: int) -> dict:
    received = sum(item["received"] for item in health.values())
    dropped = sum(item["dropped"] for item in health.values())
    loss = dropped / (received + dropped) if received + dropped else 0.0
    bad = [name for name, item in health.items() if item["status"] != "OK"]
    if health and len(bad) == len(health):
        state, reason = HealthState.BLACKOUT, "No current sensor data. Planning is withheld."
    elif bad:
        state, reason = HealthState.DEGRADED, f"Stale or silent sources: {', '.join(sorted(bad))}."
    elif loss >= 0.2:
        state, reason = HealthState.DEGRADED, f"Recent packet loss is {loss:.0%}."
    else:
        state, reason = HealthState.NOMINAL, "All current sources are healthy."
    return {"state": state.value, "reason": reason, "loss_percent": round(loss * 100, 1),
            "stale_tracks": stale_tracks, "blocked_assignments": blocked_assignments}

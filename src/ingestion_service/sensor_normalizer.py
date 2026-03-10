"""
Normalize REST and telemetry sensor payloads into a unified schema.
"""

from typing import Any


def normalize_sensor_reading(payload: dict[str, Any], source: str) -> dict[str, Any]:
    """
    Convert a raw payload (REST or telemetry) into the unified schema.

    Args:
        payload: Dictionary containing raw sensor data
        source: "rest" or "telemetry"

    Returns:
        Dictionary matching the UnifiedSensorReading schema

    Raises:
        ValueError: If the payload format is not recognized
    """
    

    base = {
        "id": payload.get("sensor_id") or payload.get("topic", "").split('/')[-1],
        "source": source,
        "captured_at": payload.get("captured_at") or payload.get("event_time", ""),
        "status": payload.get("status", "ok"),
    }

    # REST: rest.scalar.v1
    if "metric" in payload and "value" in payload and "unit" in payload:
        return {
            **base,
            "measurements": [
                {
                    "metric": payload["metric"],
                    "value": payload["value"],
                    "unit": payload["unit"],
                }
            ],
        }

    # REST: rest.particulate.v1 (before chemistry to avoid wrong match)
    if "pm1_ug_m3" in payload or "pm25_ug_m3" in payload or "pm10_ug_m3" in payload:
        return {
            **base,
            "measurements": [
                {"metric": "pm1", "value": payload.get("pm1_ug_m3", 0), "unit": "ug/m³"},
                {"metric": "pm25", "value": payload.get("pm25_ug_m3", 0), "unit": "ug/m³"},
                {"metric": "pm10", "value": payload.get("pm10_ug_m3", 0), "unit": "ug/m³"},
            ],
        }

    # REST: rest.level.v1
    if "level_pct" in payload or "level_liters" in payload:
        return {
            **base,
            "measurements": [
                {"metric": "level_pct", "value": payload.get("level_pct", 0), "unit": "%"},
                {"metric": "level_liters", "value": payload.get("level_liters", 0), "unit": "L"},
            ],
        }

    # REST: rest.chemistry.v1
    if "measurements" in payload and isinstance(payload["measurements"], list):
        measurements = payload["measurements"]
        # Ensure it is not topic.environment (that payload has a "source" object)
        if "source" not in payload or not isinstance(payload.get("source"), dict):
            return {
                **base,
                "measurements": [
                    {"metric": m["metric"], "value": m["value"], "unit": m["unit"]}
                    for m in measurements
                ],
            }

    # TELEMETRY: topic.power.v1
    if "power_kw" in payload and "voltage_v" in payload:
        return {
            **base,
            "measurements": [
                {"metric": "power", "value": payload["power_kw"], "unit": "kW"},
                {"metric": "voltage", "value": payload["voltage_v"], "unit": "V"},
                {"metric": "current", "value": payload["current_a"], "unit": "A"},
                {"metric": "cumulative_energy", "value": payload["cumulative_kwh"], "unit": "kWh"},
            ],
            "metadata": {"subsystem": payload.get("subsystem")},
        }

    # TELEMETRY: topic.environment.v1
    if "source" in payload and isinstance(payload.get("source"), dict) and "measurements" in payload:
        return {
            **base,
            "measurements": [
                {"metric": m["metric"], "value": m["value"], "unit": m["unit"]}
                for m in payload["measurements"]
            ],
            "metadata": {"source": payload["source"]},
        }

    # TELEMETRY: topic.thermal_loop.v1
    if "loop" in payload and "temperature_c" in payload:
        return {
            **base,
            "measurements": [
                {"metric": "temperature", "value": payload["temperature_c"], "unit": "°C"},
                {"metric": "flow", "value": payload["flow_l_min"], "unit": "L/min"},
            ],
            "metadata": {"loop": payload["loop"]},
        }

    # TELEMETRY: topic.airlock.v1
    if "airlock_id" in payload and "cycles_per_hour" in payload:
        return {
            **base,
            "measurements": [
                {"metric": "cycles_per_hour", "value": payload["cycles_per_hour"], "unit": "1/h"},
            ],
            "metadata": {
                "airlock_id": payload["airlock_id"],
                "last_state": payload.get("last_state"),
            },
        }

    raise ValueError(f"Unrecognized payload format: {list(payload.keys())}")

"""Prometheus queries used by the Java GC tuning prototype."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


POWER_WATT_PROMQL = (
    'avg(rate(kepler_container_joules_total{{namespace="{namespace}",pod_name="{pod_name}"}}[5m]))'
)
CPU_USAGE_PROMQL = (
    'avg(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod="{pod_name}"}}[5m]))'
)


def query_power_watt(
    prometheus_url: str,
    namespace: str,
    pod_name: str,
    start_time: float,
    end_time: float,
) -> float:
    """Return the average power in watts for a pod during the experiment window."""

    query = POWER_WATT_PROMQL.format(namespace=namespace, pod_name=pod_name)
    return _query_range_average(prometheus_url, query, start_time, end_time)


def query_cpu_usage(
    prometheus_url: str,
    namespace: str,
    pod_name: str,
    start_time: float,
    end_time: float,
) -> float:
    """Return average CPU usage for a pod during the experiment window."""

    query = CPU_USAGE_PROMQL.format(namespace=namespace, pod_name=pod_name)
    return _query_range_average(prometheus_url, query, start_time, end_time)


def _query_range_average(
    prometheus_url: str,
    query: str,
    start_time: float,
    end_time: float,
    step: str = "15s",
) -> float:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "start": start_time,
            "end": end_time,
            "step": step,
        }
    )
    url = f"{prometheus_url.rstrip('/')}/api/v1/query_range?{params}"

    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    values = _extract_values(payload)
    if not values:
        raise RuntimeError(f"Prometheus returned no values for query: {query}")
    return sum(values) / len(values)


def _extract_values(payload: dict[str, Any]) -> list[float]:
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")

    values: list[float] = []
    for series in payload.get("data", {}).get("result", []):
        for _, value in series.get("values", []):
            values.append(float(value))
    return values

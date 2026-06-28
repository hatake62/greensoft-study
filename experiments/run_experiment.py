#!/usr/bin/env python3
"""Run Java GC/heap/load experiments and append metrics to CSV."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from prometheus.queries import query_power_watt


CSV_FIELDS = [
    "gc",
    "heap",
    "load_level",
    "throughput",
    "power_watt",
    "energy_efficiency",
    "p95_latency_ms",
    "sla_ms",
    "sla_ok",
]

GC_FLAGS = {
    "G1GC": "-XX:+UseG1GC",
    "SerialGC": "-XX:+UseSerialGC",
    "ZGC": "-XX:+UseZGC",
}


@dataclass(frozen=True)
class ExperimentCase:
    gc: str
    heap: str
    load_level: int
    sla_ms: int


@dataclass(frozen=True)
class K6Result:
    throughput: float
    p95_latency_ms: float


def main() -> None:
    args = parse_args()
    matrix = load_matrix(args.matrix)
    cases = build_cases(matrix)

    args.results.parent.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(args.results)

    for case in cases:
        print(
            f"running gc={case.gc} heap={case.heap} "
            f"load={case.load_level} sla={case.sla_ms} dry_run={args.dry_run}"
        )
        row = run_case(case, args)
        append_csv(args.results, row)

    print(f"wrote {len(cases)} rows to {args.results}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=ROOT_DIR / "experiments/matrix.yaml")
    parser.add_argument("--results", type=Path, default=ROOT_DIR / "results/experiment_results.csv")
    parser.add_argument("--dry-run", action="store_true", help="Use dummy metrics without kubectl/k6/Prometheus.")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--deployment", default="java-idle-app")
    parser.add_argument("--container", default="java-container")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--target-url", default="http://localhost:8080/")
    parser.add_argument("--duration", default="30s")
    return parser.parse_args()


def load_matrix(path: Path) -> dict[str, list[Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except ImportError:
        data = _load_simple_yaml(text)

    required = {"gc", "heap", "load_level", "sla_ms"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"matrix is missing keys: {sorted(missing)}")
    return data


def _load_simple_yaml(text: str) -> dict[str, list[Any]]:
    data: dict[str, list[Any]] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":"):
            current_key = line[:-1]
            data[current_key] = []
            continue
        if line.startswith("- ") and current_key:
            value = line[2:].strip()
            data[current_key].append(int(value) if value.isdigit() else value)
            continue
        raise ValueError(f"unsupported matrix.yaml line: {raw_line}")
    return data


def build_cases(matrix: dict[str, list[Any]]) -> list[ExperimentCase]:
    return [
        ExperimentCase(gc=str(gc), heap=str(heap), load_level=int(load), sla_ms=int(sla))
        for gc, heap, load, sla in itertools.product(
            matrix["gc"], matrix["heap"], matrix["load_level"], matrix["sla_ms"]
        )
    ]


def run_case(case: ExperimentCase, args: argparse.Namespace) -> dict[str, Any]:
    if args.dry_run:
        k6_result = dummy_k6_result(case)
        power_watt = dummy_power_watt(case)
    else:
        apply_jvm_settings(args.deployment, args.container, args.namespace, case.gc, case.heap)
        restart_deployment(args.deployment, args.namespace)
        pod_name = get_pod_name(args.deployment, args.namespace)
        start_time = time.time()
        k6_result = run_k6(args.target_url, case.load_level, args.duration)
        end_time = time.time()
        power_watt = query_power_watt(
            args.prometheus_url, args.namespace, pod_name, start_time, end_time
        )

    energy_efficiency = k6_result.throughput / power_watt if power_watt > 0 else 0.0
    sla_ok = k6_result.p95_latency_ms <= case.sla_ms
    return {
        "gc": case.gc,
        "heap": case.heap,
        "load_level": case.load_level,
        "throughput": round(k6_result.throughput, 3),
        "power_watt": round(power_watt, 3),
        "energy_efficiency": round(energy_efficiency, 3),
        "p95_latency_ms": round(k6_result.p95_latency_ms, 3),
        "sla_ms": case.sla_ms,
        "sla_ok": str(sla_ok).lower(),
    }


def apply_jvm_settings(deployment: str, container: str, namespace: str, gc: str, heap: str) -> None:
    if gc not in GC_FLAGS:
        raise ValueError(f"unsupported GC: {gc}")
    java_tool_options = f"{GC_FLAGS[gc]} -Xms{heap} -Xmx{heap}"
    run_command(
        [
            "kubectl",
            "set",
            "env",
            f"deployment/{deployment}",
            f"JAVA_TOOL_OPTIONS={java_tool_options}",
            "-n",
            namespace,
        ]
    )
    run_command(
        [
            "kubectl",
            "set",
            "resources",
            f"deployment/{deployment}",
            "-c",
            container,
            f"--requests=memory={memory_for_heap(heap)}",
            f"--limits=memory={memory_for_heap(heap)}",
            "-n",
            namespace,
        ]
    )


def restart_deployment(deployment: str, namespace: str) -> None:
    run_command(["kubectl", "rollout", "restart", f"deployment/{deployment}", "-n", namespace])
    run_command(["kubectl", "rollout", "status", f"deployment/{deployment}", "-n", namespace])


def get_pod_name(deployment: str, namespace: str) -> str:
    output = run_command(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"app={deployment.replace('-app', '')}",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
    )
    if not output:
        raise RuntimeError("could not find a pod for the deployment")
    return output


def run_k6(target_url: str, load_level: int, duration: str) -> K6Result:
    script = f"""
import http from 'k6/http';
import {{ sleep }} from 'k6';

export const options = {{
  vus: {load_level},
  duration: '{duration}',
}};

export default function () {{
  http.get('{target_url}');
  sleep(1);
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = Path(handle.name)

    summary_path = script_path.with_suffix(".summary.json")
    try:
        run_command(["k6", "run", "--summary-export", str(summary_path), str(script_path)])
        return parse_k6_summary(summary_path)
    finally:
        script_path.unlink(missing_ok=True)
        summary_path.unlink(missing_ok=True)


def parse_k6_summary(path: Path) -> K6Result:
    data = json.loads(path.read_text(encoding="utf-8"))
    metrics = data.get("metrics", {})
    throughput = float(metrics["http_reqs"].get("rate", metrics["http_reqs"].get("values", {}).get("rate")))
    duration_metric = metrics["http_req_duration"]
    p95_latency = float(
        duration_metric.get("percentiles", {}).get("95")
        or duration_metric.get("values", {}).get("p(95)")
    )
    return K6Result(throughput=throughput, p95_latency_ms=p95_latency)


def memory_for_heap(heap: str) -> str:
    # Give Spring Boot and native JVM memory some room above the configured Java heap.
    return {
        "256m": "384Mi",
        "512m": "768Mi",
        "1g": "1280Mi",
    }.get(heap, heap)


def dummy_k6_result(case: ExperimentCase) -> K6Result:
    rng = random.Random(f"{case.gc}-{case.heap}-{case.load_level}-{case.sla_ms}")
    gc_factor = {"G1GC": 1.0, "SerialGC": 0.86, "ZGC": 1.08}.get(case.gc, 1.0)
    heap_factor = {"256m": 0.9, "512m": 1.0, "1g": 1.04}.get(case.heap, 1.0)
    throughput = case.load_level * gc_factor * heap_factor * rng.uniform(0.85, 1.15)
    latency = (80 + case.load_level * 5) / gc_factor / heap_factor * rng.uniform(0.9, 1.2)
    return K6Result(throughput=throughput, p95_latency_ms=latency)


def dummy_power_watt(case: ExperimentCase) -> float:
    rng = random.Random(f"power-{case.gc}-{case.heap}-{case.load_level}")
    gc_factor = {"G1GC": 1.0, "SerialGC": 0.82, "ZGC": 1.18}.get(case.gc, 1.0)
    heap_factor = {"256m": 0.92, "512m": 1.0, "1g": 1.12}.get(case.heap, 1.0)
    return (4.0 + case.load_level * 0.08) * gc_factor * heap_factor * rng.uniform(0.95, 1.08)


def run_command(command: list[str], capture_output: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture_output,
    )
    return result.stdout.strip() if capture_output else ""


def ensure_csv_header(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=CSV_FIELDS).writeheader()


def append_csv(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writerow(row)


if __name__ == "__main__":
    main()

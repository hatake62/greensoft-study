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
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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
    parser.add_argument("--http-timeout", default="5s", help="Timeout for each k6 HTTP request.")
    parser.add_argument(
        "--port-forward",
        action="store_true",
        help="Run kubectl port-forward for the deployment during each k6 run.",
    )
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
        check_prometheus_url(args.prometheus_url)
        apply_jvm_settings(args.deployment, args.container, args.namespace, case.gc, case.heap)
        restart_deployment(args.deployment, args.namespace)
        pod_name = get_pod_name(args.deployment, args.namespace)
        start_time = time.time()
        with port_forward_context(args) if args.port_forward else nullcontext():
            k6_result = run_k6(args.target_url, case.load_level, args.duration, args.http_timeout)
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


def run_k6(target_url: str, load_level: int, duration: str, http_timeout: str) -> K6Result:
    validate_target_url(target_url)
    check_target_url(target_url, duration_to_seconds(http_timeout))
    target_url_js = json.dumps(target_url)
    http_timeout_js = json.dumps(http_timeout)
    script = f"""
import http from 'k6/http';
import {{ sleep }} from 'k6';

export const options = {{
  vus: {load_level},
  duration: '{duration}',
}};

export default function () {{
  http.get({target_url_js}, {{ timeout: {http_timeout_js} }});
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
    http_reqs = metrics.get("http_reqs")
    duration_metric = metrics.get("http_req_duration")
    if not http_reqs or not duration_metric:
        metric_names = ", ".join(sorted(metrics)) or "none"
        raise RuntimeError(
            "k6 did not record any completed HTTP requests. "
            "Check that --target-url is reachable from this machine and that "
            "kubectl port-forward is still running. "
            f"Metrics in summary: {metric_names}"
        )

    failed_rate = metric_value(metrics.get("http_req_failed", {}), "rate")
    if failed_rate is not None and float(failed_rate) >= 1.0:
        raise RuntimeError(
            "k6 completed requests, but every HTTP request failed. "
            "Check --target-url, kubectl port-forward, and application logs."
        )

    throughput_value = metric_value(http_reqs, "rate")
    p95_value = metric_value(duration_metric, "p(95)", "p95", "95")
    if throughput_value is None or p95_value is None:
        raise RuntimeError(
            "k6 summary is missing expected HTTP metric values. "
            f"http_reqs keys={sorted(http_reqs.keys())}; "
            f"http_req_duration keys={sorted(duration_metric.keys())}; path={path}"
        )

    throughput = float(throughput_value)
    p95_latency = float(p95_value)
    return K6Result(throughput=throughput, p95_latency_ms=p95_latency)


def validate_target_url(target_url: str) -> None:
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"invalid --target-url: {target_url!r}. "
            "Use a full URL such as http://localhost:8080/"
        )


def check_target_url(target_url: str, timeout_seconds: float) -> None:
    request = Request(target_url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds):
            return
    except HTTPError:
        return
    except URLError as exc:
        raise RuntimeError(
            f"cannot connect to --target-url {target_url!r}: {exc.reason}. "
            "Start the application or kubectl port-forward before running experiments."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"timed out connecting to --target-url {target_url!r}. "
            "Check the application, kubectl port-forward, and --http-timeout."
        ) from exc
    except RemoteDisconnected as exc:
        raise RuntimeError(
            f"--target-url {target_url!r} closed the connection without a response. "
            "If the experiment restarted the deployment, restart kubectl port-forward "
            "or run with --port-forward."
        ) from exc


def check_prometheus_url(prometheus_url: str) -> None:
    url = f"{prometheus_url.rstrip('/')}/-/ready"
    try:
        with urlopen(url, timeout=5):
            return
    except HTTPError as exc:
        raise RuntimeError(f"Prometheus is reachable but not ready at {url!r}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"cannot connect to Prometheus at {prometheus_url!r}: {exc.reason}. "
            "Start Prometheus or run kubectl port-forward for the Prometheus service."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"timed out connecting to Prometheus at {prometheus_url!r}") from exc
    except RemoteDisconnected as exc:
        raise RuntimeError(
            f"Prometheus at {prometheus_url!r} closed the connection without a response"
        ) from exc


@contextmanager
def port_forward_context(args: argparse.Namespace) -> Iterator[None]:
    parsed = urlparse(args.target_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.port:
        raise ValueError("--port-forward requires --target-url to include a localhost port")

    process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"deployment/{args.deployment}",
            f"{parsed.port}:8080",
            "-n",
            args.namespace,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        wait_for_target_url(args.target_url, duration_to_seconds(args.http_timeout), process)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_for_target_url(target_url: str, timeout_seconds: float, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0) * 6
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("kubectl port-forward exited before the target URL became reachable")
        try:
            check_target_url(target_url, min(timeout_seconds, 1.0))
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"target URL did not become reachable after port-forward: {last_error}")


def duration_to_seconds(duration: str) -> float:
    text = duration.strip().lower()
    if text.endswith("ms"):
        return float(text[:-2]) / 1000
    if text.endswith("s"):
        return float(text[:-1])
    if text.endswith("m"):
        return float(text[:-1]) * 60
    return float(text)


def metric_value(metric: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in metric:
            return metric[name]
    for container_name in ("values", "percentiles"):
        container = metric.get(container_name, {})
        for name in names:
            if name in container:
                return container[name]
    return None


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
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("\ninterrupted by user")
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"error: {exc}") from None

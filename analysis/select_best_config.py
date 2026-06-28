#!/usr/bin/env python3
"""Print the most energy-efficient SLA-satisfying configuration per SLA."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_file)
    if not rows:
        print("no rows found")
        return

    for sla_ms in sorted({int(row["sla_ms"]) for row in rows}):
        candidates = [
            row for row in rows if int(row["sla_ms"]) == sla_ms and parse_bool(row["sla_ok"])
        ]
        print(f"SLA {sla_ms}ms:")
        if not candidates:
            print("best = none (no SLA-satisfying rows)")
            continue
        best = max(candidates, key=lambda row: float(row["energy_efficiency"]))
        print(
            "best = "
            f"{best['gc']}, heap={best['heap']}, load={best['load_level']}, "
            f"energy_efficiency={best['energy_efficiency']}, "
            f"p95_latency={best['p95_latency_ms']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


if __name__ == "__main__":
    main()

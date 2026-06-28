#!/usr/bin/env python3
"""Plot p95 latency vs energy efficiency from experiment CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_file)
    if not rows:
        raise SystemExit("no rows found")

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        plot(rows, output)
    except ImportError as exc:
        raise SystemExit(f"matplotlib is required to create the graph: {exc}") from exc
    except Exception as exc:
        raise SystemExit(f"failed to create graph: {exc}") from exc

    print(f"wrote {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/pareto_front.png"))
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def plot(rows: list[dict[str, str]], output: Path) -> None:
    import matplotlib.pyplot as plt

    x = [float(row["p95_latency_ms"]) for row in rows]
    y = [float(row["energy_efficiency"]) for row in rows]
    labels = [f"{row['gc']} {row['heap']}" for row in rows]

    plt.figure(figsize=(10, 6))
    plt.scatter(x, y)
    for x_value, y_value, label in zip(x, y, labels):
        plt.annotate(label, (x_value, y_value), fontsize=8, alpha=0.75)

    plt.xlabel("P95 latency (ms)")
    plt.ylabel("Energy efficiency (req/s/W)")
    plt.title("Java GC tuning Pareto front")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output, dpi=160)
    plt.close()


if __name__ == "__main__":
    main()

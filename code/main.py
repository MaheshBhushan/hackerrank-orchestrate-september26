"""Run from any directory: python3 code/main.py [--samples]."""

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.validation import verify
from evidence import Dataset, read_csv
from finance import forecast
from planner import solve

FIELDS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def main():
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    parser.add_argument("--dataset", type=Path, default=root / "dataset")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", action="store_true")
    parser.add_argument("--estimator", choices=["mean", "mean3", "max"], default="mean")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "evaluation",
    )
    args = parser.parse_args()
    dataset = Dataset(args.dataset)
    requests = read_csv(
        args.dataset / ("sample_requests.csv" if args.samples else "requests.csv")
    )
    rows = []
    audits = []
    for request in requests:
        profile, flows, streams, _ = forecast(dataset, request, args.estimator)
        row, chosen, _ = solve(dataset, request, profile, flows, streams)
        audit = verify(dataset, request, row, profile, flows, streams)
        audit.update(
            request_id=request["request_id"],
            payment_option_id=chosen.option_id if chosen else "",
            forecast_events=len(flows),
            inferred_recurring_expenses=len(streams),
        )
        audits.append(audit)
        rows.append(row)
    if len({r["request_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate request IDs")
    target = args.output or root / (
        "sample_predictions.csv" if args.samples else "output.csv"
    )
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} predictions to {target}")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    if args.samples:
        from evaluation.evaluate_samples import evaluate

        report = evaluate(requests, rows)
        (args.report_dir / "sample_metrics.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    else:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requests": len(rows),
            "estimator": args.estimator,
            "horizon_days": 90,
            "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "input_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(args.dataset.glob("*.csv"))
                if p.name != "sample_requests.csv"
            },
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model_cost_usd": 0,
            "audit": audits,
        }
        (args.report_dir / "run_report.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()

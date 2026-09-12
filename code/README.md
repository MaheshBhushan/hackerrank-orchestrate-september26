# Buy or Wait? — evidence-grounded cash-flow planner

Python 3.10+; standard library only. No API keys, live exchange rates, or network access are required by the prediction run.

## Run

Keep the supplied participant CSVs and images in `dataset/` and extract this code archive into `code/` beside it. From the repository root:

```sh
python3 code/main.py
python3 code/main.py --samples
PYTHONPATH=code python3 -m unittest discover -s code/evaluation -p 'test_*.py' -v
```

The first command generates root-level `output.csv`, verifies each row before writing it, and creates `code/evaluation/run_report.json`. The second generates separate public-sample predictions and metrics. Sample target columns are not loaded by the prediction path.

Custom paths:

```sh
python3 code/main.py --dataset /path/to/dataset --output /path/to/output.csv --report-dir /path/to/reports
```

## Implementation

- `evidence.py`: CSV loading, joins, content-addressed image extraction cache, English/Indonesian payroll evidence.
- `image_facts.json`: 16 extracted image facts, source SHA-256 hashes, currencies, and short supporting quotations/descriptions. These are document facts, not request answers. Every image was visually reviewed in Codex; OCR assisted the review. Missing or changed images fail explicitly.
- `finance.py`: currency conversion, recurrence inference, dated cash flows, and safe-payment capacity.
- `planner.py`: full payment, partial payment, supplied installment offers, waiting, up to three permitted spending changes, and deterministic ranking.
- `evaluation/validation.py`: independent event-by-event cash replay, exhaustive earliest-date verification, safe-amount maximality, schedule/eligibility/deadline checks.
- `evaluation/test_engine.py`: 19 hand-calculated regression tests.
- `evaluation/evaluate_samples.py`: separate public-label evaluation.

All cash amounts use integer hundredths; Decimal handles parsing, FX and rounding. Installments preserve the supplied equal-payment schedule; financing fees are not added twice. The aggregate rounding difference from the supplied total is checked rather than silently changing the last installment.

## Forecast assumptions and limits

The specification does not provide a unique estimator for variable spending or a same-day settlement order. This implementation explicitly uses:

1. The current balance already includes historical settled transactions. Historical receipts are not debited again.
2. Same-day confirmed income settles before bills; request payments follow the bills. Opening balance and every cash event are independently checked.
3. The forecast includes request day through request day plus 90 days, inclusive.
4. Repeated monthly bills retain their calendar day. Other recurring expenses use their demonstrated median interval; groceries, transport and dining are grouped by category to accommodate varying merchants. At least two records and a consistent cadence are required.
5. The mean of the last three comparable observations estimates variable spending. This is an estimate, not a guarantee or an organizer-specified formula. `--estimator max` is an available more conservative stress scenario; it performed worse on the supplied samples and is not the submitted baseline.
6. Salary is distinguished from bonuses, commissions, arrears, irregular work and final employment payments. Explicit payroll amendments override older amounts; unconfirmed windfalls and pending credits add no cash. Confirmed one-off invoice payments and payroll arrears are counted once.
7. Stopping/reducing applies only to an inferred recurring stream that the user's flexibility and protected-category preferences permit. Reductions use the supplied minimum allowed amount. Unchanged plans always outrank changed plans.
8. `max_installment_months` is interpreted as the maximum count of monthly installments. Supplied installment intervals are 28–31 days; schedules must also finish within the request deadline and forecast horizon.
9. Unknown financial amounts cause failure. An unspecified future expense amount (for example a message mentioning new childcare without a matching amount) is not invented.

The final CSV is a reproducible candidate answer set. Exact hidden-test correctness is not established. See `evaluation/results.md` for the material sample discrepancies; do not present the financial verifier as proof of agreement with hidden labels or certainty about future spending.

## Repackage

```sh
python3 code/evaluation/package_solution.py
```

This writes `code.zip` with the solution contents and root-level `evaluation/usage_report.md`. Dataset files, development logs, Python caches, and credentials are excluded.

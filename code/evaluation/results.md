# Evaluation and remaining uncertainty

The final full-dataset run produced exactly 250 unique request rows. The local `requests.csv` and the repository's `dataset/requests.csv` were byte-identical. No organizer-only data or request-answer lookup table was used.

## Verification

- 29 hand-calculated regression tests passed (cash engine plus evidence-contract cases: message cancellations/settlements/amendments, linked-event handling, ended employment superseded by a confirmed new salary, opening balance below the reserve).
- Every row passed bounds, method, deadline and format checks.
- All positive recommendations passed an independent event-level cash replay, including the allowed changes and the whole forecast; the remaining rows recommend no payment.
- Every reported safe amount was checked for feasibility and one-cent maximality when the baseline was feasible; unsafe baselines correctly report zero.
- Every earliest full-payment date was checked by independently replaying every preceding candidate date.
- Supplied installment schedules, payment preferences and flexible-expense permissions were checked.
- Code Health fast and deep checks were clean after formatting/import fixes.

These checks establish internal correctness against the reconstructed forecast. They do not establish the accuracy of inferred future spending.

## Public sample agreement

| Structured field | Exact matches | Accuracy |
| --- | ---: | ---: |
| Safe amount | 3/25 | 12% |
| Affordability status | 20/25 | 80% |
| Payment method | 22/25 | 88% |
| Payment plan | 21/25 | 84% |
| Earliest full-payment date | 19/25 | 76% |
| Spending changes | 20/25 | 80% |

Mean absolute safe-amount error, normalized by each requested amount, is 3.30% (down from 7.39% with the earlier last-three-observation estimator and description-whitelisted salary). Do not combine raw monetary errors from different currencies into a claimed monetary accuracy figure. Numeric formatting differences such as `620.4` versus `620.40` are normalized during scoring.

Full per-request differences are in `sample_metrics.json`. The estimator is not calibrated to reproduce example labels, and no public example prediction is replaced by its expected answer.

## What the sample labels reveal

Subtracting each expected safe amount from the opening balance minus the reserve gives the organizer's forecast outflow at the balance trough. Those implied totals are whole numbers even when the user's utilities and variable spending carry cents (for example 452.00, 487.00, 624, 157.00, 140430.00), so the labels appear to be generated from noise-free underlying amounts rather than from any statistic of the noisy history. Exact agreement is therefore mostly unattainable from the supplied data; the estimator was chosen to minimize error instead. Two changes followed from this: averaging the full history (more observations, less noise), and reading the underlying amount from `minimum_allowed_amount`, which sits at 50% or 40% of it. The freelance/contract income of `request_09` (two contract payments a month with varying descriptions) is also counted as regular income, while weekly gig-platform payouts (`request_10`, with a "payout still pending" notice) are not; both choices match the sample labels.

A grid search over estimator (mean/median/max/last, several windows), rounding, same-day ordering, request-day handling and horizon length found no configuration matching more than 3 of 25 safe amounts exactly, which supports the noise-free-label explanation. End-of-day versus intraday balance checking made no difference on the samples.

## Why exact amounts remain unresolved

The challenge requires recurrence detection and conservative variable-spending forecasts, but does not specify the observation window, estimator, outlier rule, rounding convention, or projected dates for variable expenses. Reasonable choices change both safe amounts and the dates at which full payment becomes feasible. The current three-observation mean and historical cadence are explicit, reproducible assumptions; they are not asserted to be the hidden organizer model.

The maximum-of-three stress scenario was also evaluated. It reduced public method agreement to 18/25 and safe-amount agreement to 1/25, so simply inflating every expense does not explain the sample answers.

There are also evidence/label tensions worth clarifying:

- `request_11`: employer `message_08` explicitly states a confirmed base salary of IDR 38,760,000. Older `Base salary` events show IDR 23,256,000. Following the explicit amendment produces a safe full-payment date of 2025-05-15 under this forecast; the sample says 2025-07-15 and recommends spending changes. A different expense model may contribute, but ignoring the amendment is not justified by the stated conflict order.
- `request_21`: under observed expense cadence, the full USD 1,574.40 is feasible today without changes, whereas the sample requires stopping storage and reducing streaming. The discrepancy is in forecast construction rather than installment or ranking logic.
- `request_06`: the inferred recurring expense dates leave only EUR 527.52 safe today, compared with EUR 603.30 in the sample. Stopping the EUR 19 streaming plan does not make today's EUR 620.40 payment safe under this reconstructed timeline.

The most valuable next clarification is the organizer's exact variable-expense forecasting convention and how salary amendments should interact with the samples. Hidden-test accuracy cannot be certified from the supplied rules alone. Treat the current output as a validated draft rather than a demonstrated high-accuracy submission.

## Audit artifacts

`run_report.json` records input/output hashes, the forecast estimator, the selected option ID for each request, validation results, minimum projected balances for positive recommendations, and final-run model usage. `image_facts.json` records only extracted document facts and hashes; it contains no payment-plan labels.

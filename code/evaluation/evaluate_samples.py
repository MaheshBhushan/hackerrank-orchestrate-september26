"""Public sample scoring: never imported during an evaluation-request solve."""

from decimal import Decimal


def normalize(field, value):
    if field == "amount_safe_to_pay":
        return Decimal(value)
    if field == "payment_plan" and value != "none":
        return tuple(
            (p.split(":")[0], Decimal(p.split(":")[1])) for p in value.split("|")
        )
    if field == "spending_changes_needed":
        return frozenset(
            tuple(p.split(":")[:2])
            + ((Decimal(p.split(":")[2]),) if p.startswith("reduce_to:") else ())
            for p in value.split("|")
        )
    return value


def evaluate(expected, actual):
    fields = [
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
    ]
    scores = dict.fromkeys(fields, 0)
    failures = []
    absolute_errors = []
    relative_errors = []
    for truth, prediction in zip(expected, actual):
        differences = []
        for field in fields:
            same = normalize(field, truth[field]) == normalize(field, prediction[field])
            scores[field] += same
            if not same:
                differences.append(
                    f"{field}: {prediction[field]} (expected {truth[field]})"
                )
        if differences:
            print(truth["request_id"], "\n  " + "\n  ".join(differences))
            failures.append(
                {"request_id": truth["request_id"], "differences": differences}
            )
        error = abs(
            Decimal(truth["amount_safe_to_pay"])
            - Decimal(prediction["amount_safe_to_pay"])
        )
        absolute_errors.append(error)
        relative_errors.append(error / Decimal(truth["requested_amount"]))
    for field, count in scores.items():
        print(f"{field}: {count}/{len(expected)}")
    return {
        "samples": len(expected),
        "matches": scores,
        "mismatches": failures,
        "safe_amount_mae_mixed_currencies": float(sum(absolute_errors) / len(expected)),
        "safe_amount_mae_fraction_of_request": float(
            sum(relative_errors) / len(expected)
        ),
    }

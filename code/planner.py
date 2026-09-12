"""Enumerate eligible schedules, verify cash safety and rank deterministically."""

import re
from datetime import date, timedelta
from itertools import combinations, product

from finance import balances, capacity
from models import Plan, cents, money


def safe_plan(profile, values, start, payments):
    floor = cents(profile["minimum_balance_to_keep"])
    if cents(profile["current_available_balance"]) < floor:
        return False
    paid = 0
    by_day = {}
    for day, amount in payments:
        if amount <= 0 or day < start or (day - start).days >= len(values):
            return False
        by_day[day] = by_day.get(day, 0) + amount
    for i, balance in enumerate(values):
        paid += by_day.get(start + timedelta(days=i), 0)
        if balance - paid < floor:
            return False
    return True


def change_sets(profile, streams):
    choices = []
    protected = set(profile["expense_categories_to_protect"].split("|"))
    stop = set(profile["expense_categories_user_is_willing_to_stop"].split("|"))
    reduce = set(profile["expense_categories_user_is_willing_to_reduce"].split("|"))
    for s in streams:
        options = []
        if s.category in protected or not s.dates:
            continue
        if s.category in stop and s.flexibility in (
            "stoppable",
            "reducible_or_stoppable",
        ):
            options.append((s.event_id, 0))
        if (
            s.category in reduce
            and s.flexibility in ("reducible", "reducible_or_stoppable")
            and s.minimum < s.amount
        ):
            options.append((s.event_id, s.minimum))
        if options:
            choices.append(options)
    yield ()
    for n in range(1, min(3, len(choices)) + 1):
        for subset in combinations(choices, n):
            yield from product(*subset)


def candidates(dataset, request, profile, values, start, safe_today, earliest, changes):
    allowed = set(profile["payment_methods_user_will_consider"].split("|"))
    amount = cents(request["requested_amount"])
    deadline = date.fromisoformat(request["desired_completion_date"])
    possible = []
    if "full_payment" in allowed:
        possible.append(Plan("full_payment", ((start, amount),), changes, cost=amount))
        _, new_earliest = capacity(profile, values, amount)
        if new_earliest is not None and new_earliest > 0:
            possible.append(
                Plan(
                    "wait",
                    ((start + timedelta(days=new_earliest), amount),),
                    changes,
                    cost=amount,
                )
            )
    if (
        "partial_payment" in allowed
        and request["allows_partial_payment"] == "true"
        and 0 < safe_today < amount
        and earliest is not None
        and earliest > 0
    ):
        possible.append(
            Plan(
                "partial_payment",
                (
                    (start, safe_today),
                    (start + timedelta(days=earliest), amount - safe_today),
                ),
                changes,
                cost=amount,
            )
        )
    if "installments" in allowed:
        maximum = int(profile["max_installment_months"] or "0")
        for option in dataset.options[request["request_id"]]:
            if option["payment_method"] != "installments":
                continue
            n = int(option["number_of_payments"])
            if n > maximum:
                continue
            first = date.fromisoformat(option["first_payment_date"])
            step = int(option["payment_frequency_days"] or "0")
            payments = tuple(
                (first + timedelta(days=step * i), cents(option["payment_amount"]))
                for i in range(n)
            )
            possible.append(
                Plan(
                    "installments",
                    payments,
                    changes,
                    option["payment_option_id"],
                    cents(option["total_payable_amount"]),
                )
            )
    return [
        p
        for p in possible
        if p.payments[-1][0] <= deadline
        and safe_plan(profile, values, start, p.payments)
    ]


def rank(plan):
    option_order = int(re.search(r"\d+$", plan.option_id)[0]) if plan.option_id else -1
    return (
        bool(plan.changes),
        plan.cost,
        plan.payments[0][0],
        len(plan.payments),
        option_order,
        len(plan.changes),
        plan.changes,
    )


def solve(dataset, request, profile, flows, streams):
    start = date.fromisoformat(request["request_date"])
    values = balances(profile, flows, start)
    amount = cents(request["requested_amount"])
    safe_today, earliest = capacity(profile, values, amount)
    safe_candidates = []
    for changes in change_sets(profile, streams):
        # Any safe unchanged plan outranks every plan that needs a change.
        if changes and safe_candidates and not safe_candidates[0].changes:
            break
        modified = balances(profile, flows, start, changes) if changes else values
        safe_candidates.extend(
            candidates(
                dataset,
                request,
                profile,
                modified,
                start,
                safe_today,
                earliest,
                changes,
            )
        )
    chosen = min(safe_candidates, key=rank) if safe_candidates else None
    if chosen is None:
        status, method = "not_affordable", "not_recommended"
    elif chosen.changes or chosen.method in ("partial_payment", "installments"):
        status, method = "affordable_with_plan", chosen.method
    elif chosen.method == "wait":
        status, method = "affordable_later", "wait"
    else:
        status, method = "affordable_now", "full_payment"
    plan_text = (
        "|".join(f"{d}:{money(a)}" for d, a in chosen.payments) if chosen else "none"
    )
    changes_text = (
        "|".join(
            f"stop:{e}" if a == 0 else f"reduce_to:{e}:{money(a)}"
            for e, a in chosen.changes
        )
        if chosen and chosen.changes
        else "none"
    )
    currency = profile["home_currency"]
    explanation = f"{money(safe_today)} {currency} is safe today before optional changes; the reserve is {profile['minimum_balance_to_keep']} {currency}. "
    if chosen:
        explanation += f"{method.replace('_', ' ').capitalize()}: complete payment by {chosen.payments[-1][0]}."
        if chosen.changes:
            explanation += f" Requires {changes_text}."
        checked = balances(profile, flows, start, chosen.changes)
        paid = 0
        daily = dict(chosen.payments)
        trough = []
        for i, b in enumerate(checked):
            paid += daily.get(start + timedelta(days=i), 0)
            trough.append(b - paid)
        explanation += (
            f" Forecast minimum after payments: {money(min(trough))} {currency}."
        )
    else:
        explanation += f"No permitted plan completes the request by {request['desired_completion_date']} while passing the 90-day reserve check."
    row = {
        "request_id": request["request_id"],
        "amount_safe_to_pay": money(safe_today),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_text,
        "earliest_date_for_full_payment": (start + timedelta(days=earliest)).isoformat()
        if earliest is not None
        else "",
        "spending_changes_needed": changes_text,
        "decision_explanation": explanation,
    }
    return row, chosen, values

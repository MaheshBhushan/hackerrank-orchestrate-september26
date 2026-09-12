"""Independent event-level verification of the emitted financial contract."""

from collections import defaultdict
from datetime import date, timedelta

from models import cents


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_payments(text):
    if text == "none":
        return ()
    return tuple(
        (date.fromisoformat(x.split(":")[0]), cents(x.split(":")[1]))
        for x in text.split("|")
    )


def parse_changes(text):
    if text == "none":
        return ()
    out = []
    for text_action in text.split("|"):
        parts = text_action.split(":")
        require(parts[0] in ("stop", "reduce_to"), "Unknown spending action")
        require(
            len(parts) == (2 if parts[0] == "stop" else 3), "Malformed spending action"
        )
        out.append((parts[1], 0 if parts[0] == "stop" else cents(parts[2]), parts[0]))
    return tuple(out)


def replay(profile, flows, start, payments=(), changes=()):
    """Include opening cash and every event, including interim payments."""
    by_day = defaultdict(list)
    overrides = dict(changes)
    for flow in flows:
        amount = (
            -overrides[flow.event_id]
            if flow.amount < 0 and flow.event_id in overrides
            else flow.amount
        )
        by_day[flow.day].append((0 if amount > 0 else 1, flow.event_id, amount))
    for i, (d, amount) in enumerate(payments):
        by_day[d].append((2, f"payment_{i}", -amount))
    balance = cents(profile["current_available_balance"])
    floor = cents(profile["minimum_balance_to_keep"])
    minimum, minimum_day = balance, start
    for day in sorted(by_day):
        require(
            start <= day <= start + timedelta(days=90), "Cash event outside forecast"
        )
        for _, _, amount in sorted(by_day[day]):
            balance += amount
            if balance < minimum:
                minimum, minimum_day = balance, day
    return minimum >= floor, minimum, minimum_day


def verify(dataset, request, row, profile, flows, streams):
    start = date.fromisoformat(request["request_date"])
    end = start + timedelta(days=90)
    requested = cents(request["requested_amount"])
    safe_amount = cents(row["amount_safe_to_pay"])
    require(0 <= safe_amount <= requested, "Invalid safe amount bounds")
    baseline_safe, _, _ = replay(profile, flows, start)
    if baseline_safe:
        require(
            replay(profile, flows, start, ((start, safe_amount),))[0],
            "Safe amount fails cash replay",
        )
        if safe_amount < requested:
            require(
                not replay(profile, flows, start, ((start, safe_amount + 1),))[0],
                "Safe amount is not maximal",
            )
    else:
        require(safe_amount == 0, "Unsafe baseline cannot support an immediate payment")
    earliest = None
    for offset in range(91):
        d = start + timedelta(days=offset)
        if replay(profile, flows, start, ((d, requested),))[0]:
            earliest = d
            break
    require(
        row["earliest_date_for_full_payment"]
        == (earliest.isoformat() if earliest else ""),
        "Earliest date fails independent search",
    )
    payments = parse_payments(row["payment_plan"])
    changes = parse_changes(row["spending_changes_needed"])
    require(
        len(changes) <= 3 and len({e for e, _, _ in changes}) == len(changes),
        "Conflicting or excessive changes",
    )
    stream_map = {s.event_id: s for s in streams}
    protected = set(profile["expense_categories_to_protect"].split("|"))
    for event_id, amount, action in changes:
        require(event_id in stream_map, "Changed event is not recurring")
        stream = stream_map[event_id]
        require(stream.category not in protected, "Protected expense was changed")
        if action == "stop":
            require(
                stream.category
                in profile["expense_categories_user_is_willing_to_stop"].split("|"),
                "Stop preference violated",
            )
            require(
                stream.flexibility in ("stoppable", "reducible_or_stoppable"),
                "Event cannot be stopped",
            )
        else:
            require(
                stream.category
                in profile["expense_categories_user_is_willing_to_reduce"].split("|"),
                "Reduction preference violated",
            )
            require(
                stream.flexibility in ("reducible", "reducible_or_stoppable"),
                "Event cannot be reduced",
            )
            require(
                stream.minimum <= amount < stream.amount,
                "Reduction outside allowed bounds",
            )
    method = row["recommended_payment_method"]
    status = row["affordability_status"]
    require(
        method
        in (
            "full_payment",
            "partial_payment",
            "installments",
            "wait",
            "not_recommended",
        ),
        "Invalid method",
    )
    require(
        status
        in (
            "affordable_now",
            "affordable_with_plan",
            "affordable_later",
            "not_affordable",
        ),
        "Invalid status",
    )
    if method == "not_recommended":
        require(
            status == "not_affordable" and not payments and not changes,
            "Invalid fallback",
        )
        return {"safe": None, "baseline_safe": baseline_safe}
    require(
        payments and all(a > 0 for _, a in payments), "Empty or nonpositive schedule"
    )
    require(tuple(sorted(payments)) == payments, "Non-chronological schedule")
    require(
        start
        <= payments[0][0]
        <= payments[-1][0]
        <= min(end, date.fromisoformat(request["desired_completion_date"])),
        "Schedule misses deadline/horizon",
    )
    allowed = profile["payment_methods_user_will_consider"].split("|")
    require(
        ("full_payment" if method == "wait" else method) in allowed,
        "Payment preference violated",
    )
    if method == "partial_payment":
        require(
            request["allows_partial_payment"] == "true"
            and 0 < safe_amount < requested
            and earliest is not None,
            "Partial payment ineligible",
        )
        require(
            payments == ((start, safe_amount), (earliest, requested - safe_amount)),
            "Incorrect partial schedule",
        )
    elif method in ("full_payment", "wait"):
        require(
            len(payments) == 1 and payments[0][1] == requested, "Incorrect full payment"
        )
        require(
            (method == "wait") == (payments[0][0] > start), "Incorrect wait/full method"
        )
    else:
        matches = []
        for option in dataset.options[request["request_id"]]:
            if option["payment_method"] != "installments":
                continue
            n = int(option["number_of_payments"])
            first = date.fromisoformat(option["first_payment_date"])
            days = int(option["payment_frequency_days"])
            schedule = tuple(
                (first + timedelta(days=days * i), cents(option["payment_amount"]))
                for i in range(n)
            )
            if schedule == payments and n <= int(
                profile["max_installment_months"] or "0"
            ):
                # Equal installments are supplied rounded to cents. Keep them
                # exact, allowing only the aggregate rounding discrepancy.
                require(
                    abs(
                        sum(a for _, a in payments)
                        - cents(option["total_payable_amount"])
                    )
                    <= (n + 1) // 2,
                    "Unexplained installment total discrepancy",
                )
                matches.append(option["payment_option_id"])
        require(
            matches, "Installment schedule does not match an eligible supplied option"
        )
    expected_status = (
        "affordable_with_plan"
        if changes or method in ("partial_payment", "installments")
        else "affordable_later"
        if method == "wait"
        else "affordable_now"
    )
    require(status == expected_status, "Status does not match plan")
    result = replay(
        profile, flows, start, payments, tuple((e, a) for e, a, _ in changes)
    )
    require(result[0], "Recommended plan breaches minimum balance")
    return {
        "safe": True,
        "minimum_balance": result[1] / 100,
        "minimum_date": str(result[2]),
        "baseline_safe": baseline_safe,
    }

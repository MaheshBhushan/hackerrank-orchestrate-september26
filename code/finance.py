"""Conservative recurrence inference and a fixed 90-day cash timeline."""

import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from evidence import payroll_facts, resolve_message_amendments
from models import Cash, Stream, cents


def month_date(day, offset, anchor=None):
    y, m = divmod(day.year * 12 + day.month - 1 + offset, 12)
    return date(y, m + 1, min(anchor or day.day, calendar.monthrange(y, m + 1)[1]))


def schedule(last, start, end, interval=None):
    result = []
    for n in range(1, 200):
        d = last + timedelta(days=interval * n) if interval else month_date(last, n)
        if d > end:
            break
        if d >= start:
            result.append(d)
    return tuple(result)


def fx(dataset, amount, currency, home, day):
    if currency == home:
        return cents(amount)
    key = (day.isoformat(), currency, home)
    if key not in dataset.rates:
        raise ValueError(f"Missing settlement-date FX: {key}")
    return cents(Decimal(str(amount)) * Decimal(dataset.rates[key]))


def base_from_minimum(event, estimate, home):
    """Recover the underlying recurring amount from a reducible item's floor.

    Supplied ``minimum_allowed_amount`` values sit at either 50% or 40% of the
    unobserved base amount (the dataset's two clusters). When the floor is in
    the item's own currency, whichever base is nearer the historical mean is a
    less noisy estimate than the mean itself.
    """
    if not event["minimum_allowed_amount"] or event["currency"] != home:
        return estimate
    floor = cents(event["minimum_allowed_amount"])
    if floor <= 0 or estimate <= 0:
        return estimate
    ratio = floor / estimate
    if 0.44 <= ratio <= 0.58:
        return floor * 2
    if 0.32 <= ratio < 0.44:
        return int(round(floor * 2.5))
    return estimate


REGULAR_INCOME = {
    "Payroll credit",
    "Base salary",
    "Primary household salary",
    "Second household income",
    "First-job payroll",
    "New employer payroll",
    "International employer payroll",
    "Payroll after returning from leave",
    "Next confirmed salary",
    "Website project payment",
    "Content contract payment",
    "Freelance milestone payment",
    "Consulting invoice payment",
    "Independent work payment",
    "Application project payment",
    "Design contract payment",
    "Client retainer payment",
}


def forecast(dataset, request, estimator="mean"):
    profile = dataset.profiles[request["user_id"]]
    start = date.fromisoformat(request["request_date"])
    end = start + timedelta(days=90)
    home = profile["home_currency"]
    messages = dataset.messages[request["user_id"]]
    events = resolve_message_amendments(dataset.resolved_events(request), messages, request)
    facts = payroll_facts(messages, request)
    flows, streams, notes = [], [], []
    groups = defaultdict(list)
    histories = []
    successors = {
        e["linked_event_id"]: e
        for e in events
        if e["linked_event_id"] and e["status"] in ("settled", "scheduled")
    }
    for e in events:
        if e["status"] in ("cancelled", "failed", "unrealized"):
            continue
        d = date.fromisoformat(e["settlement_date"] or e["event_date"])
        if e["direction"] == "credit" and e["status"] == "pending":
            continue
        successor = successors.get(e["event_id"])
        if (
            successor
            and successor["direction"] == e["direction"]
            and successor["category"] == e["category"]
            and successor["amount"] == e["amount"]
            and successor["currency"] == e["currency"]
        ):
            # A link plus identical amount marks a retry/duplicate of this row.
            continue
        if e["category"] == "salary" and e["direction"] == "credit":
            histories.append(e)
            continue
        if e["status"] in ("pending", "scheduled") or d >= start:
            if e["direction"] == "debit" or e["status"] == "settled":
                when = max(start, d)
                if when <= end:
                    amount = fx(dataset, e["amount"], e["currency"], home, d)
                    flows.append(
                        Cash(
                            when,
                            amount if e["direction"] == "credit" else -amount,
                            e["event_id"],
                            e["description"],
                        )
                    )
            continue
        if e["direction"] == "debit" and e["event_type"] in (
            "expense",
            "subscription",
            "debt_payment",
        ):
            if e.get("_image") or e["linked_event_id"]:
                continue
            key = (
                e["category"],
                ""
                if e["category"] in ("groceries", "transport", "dining")
                else e["description"],
            )
            groups[key].append(e)
    for (cat, _), group in groups.items():
        group.sort(key=lambda e: e["settlement_date"])
        if len(group) < 2:
            continue
        ds = [date.fromisoformat(e["settlement_date"]) for e in group]
        gaps = [(b - a).days for a, b in pairwise(ds) if b > a]
        if not gaps:
            continue
        median_gap = int(statistics.median(gaps))
        monthly = len({d.day for d in ds}) == 1 and 27 <= median_gap <= 32
        if not monthly and (
            median_gap < 2
            or median_gap > 35
            or sum(abs(g - median_gap) <= 1 for g in gaps) / len(gaps) < 0.7
        ):
            continue
        if (start - ds[-1]).days > (45 if monthly else median_gap * 2):
            continue
        window = group[-3:] if estimator in ("mean3", "max") else group
        values = [
            fx(
                dataset,
                e["amount"],
                e["currency"],
                home,
                date.fromisoformat(e["settlement_date"]),
            )
            for e in window
        ]
        amount = (
            max(values)
            if estimator == "max"
            else cents(Decimal(sum(values)) / (len(values) * 100))
        )
        e = group[-1]
        amount = base_from_minimum(e, amount, home)
        if cat == "rent" and "rent_increase" in facts:
            amount = cents(
                Decimal(amount) / 100 * (1 + Decimal(facts["rent_increase"]) / 100)
            )
        dates = schedule(ds[-1], start, end, None if monthly else median_gap)
        streams.append(
            Stream(
                e["event_id"],
                cat,
                e["description"],
                amount,
                dates,
                e["flexibility"],
                cents(e["minimum_allowed_amount"] or "0"),
            )
        )
    # Salary evidence is kept separate from cash refunds, arrears, prizes,
    # seasonal earnings, commissions and weekly gig/platform payouts. Regular
    # income may arrive more than once a month (e.g. two contract payments), so
    # each calendar-day-of-month cluster is projected as its own monthly stream.
    regular = sorted(
        (e for e in histories if e["description"] in REGULAR_INCOME),
        key=lambda e: e["settlement_date"],
    )
    # An explicit, confirmed employer amount after a final payroll supersedes
    # the ended-employment inference; an explicit "ended" notice wins otherwise.
    ended = (
        facts["ended"]
        if "ended" in facts
        else any(e["description"] == "Final employer payroll" for e in histories)
    )
    clusters = defaultdict(list)
    for e in regular:
        d = date.fromisoformat(e["settlement_date"])
        if (start - d).days <= 62:
            clusters[d.day].append(e)
    stale = {
        day
        for day, group in clusters.items()
        if (start - date.fromisoformat(group[-1]["settlement_date"])).days > 45
    }
    for day in stale:
        del clusters[day]
    if not ended and (clusters or facts.get("amount")):
        if not clusters:
            first = (
                date.fromisoformat(facts["date"])
                if "date" in facts
                else month_date(start.replace(day=15), 1 if start.day > 15 else 0)
            )
            clusters[first.day] = []
        primary = max(clusters, key=lambda day: len(clusters[day]))
        for day, group in clusters.items():
            last = group[-1] if group else None
            if day == primary or not group:
                amount = facts.get("amount", last["amount"] if last else None)
                currency = facts.get("currency", last["currency"] if last else home)
            else:
                amount, currency = last["amount"], last["currency"]
            if amount is None:
                continue
            if "date" in facts and (day == primary or not group):
                first = date.fromisoformat(facts["date"])
            elif last:
                first = date.fromisoformat(last["settlement_date"])
                while first < start:
                    first = month_date(first, 1, day)
            else:
                first = month_date(start.replace(day=15), 1 if start.day > 15 else 0)
            for n in range(5):
                pay_day = month_date(first, n, first.day)
                if start <= pay_day <= end:
                    value = fx(dataset, amount, currency, home, pay_day)
                    source = facts.get("source") if (day == primary or not group) else None
                    flows.append(
                        Cash(
                            pay_day,
                            value,
                            source or (last["event_id"] if last else "salary"),
                            "Confirmed recurring salary",
                        )
                    )
                    if n == 0 and facts.get("arrears") and (day == primary or not group):
                        flows.append(
                            Cash(
                                pay_day,
                                fx(dataset, facts["arrears"], currency, home, pay_day),
                                facts["source"] + ":arrears",
                                "Confirmed one-time payroll arrears",
                            )
                        )
    if facts.get("invoice"):
        currency, amount, d, eid = facts["invoice"]
        day = date.fromisoformat(d)
        if start <= day <= end:
            flows.append(
                Cash(
                    day,
                    fx(dataset, amount, currency, home, day),
                    eid,
                    "Confirmed invoice payment",
                )
            )
    for s in streams:
        for d in s.dates:
            flows.append(Cash(d, -s.amount, s.event_id, s.description))
    return profile, flows, streams, notes


def balances(profile, flows, start, changes=()):
    """Income settles before expenses; payments occur after that day's bills."""
    adjustments = dict(changes)
    grouped = defaultdict(list)
    for flow in flows:
        grouped[flow.day].append(flow)
    balance = cents(profile["current_available_balance"])
    result = []
    for offset in range(91):
        d = start + timedelta(days=offset)
        for flow in sorted(grouped[d], key=lambda f: -f.amount):
            value = (
                -adjustments[flow.event_id]
                if flow.event_id in adjustments and flow.amount < 0
                else flow.amount
            )
            balance += value
        result.append(balance)
    return result


def capacity(profile, values, requested):
    floor = cents(profile["minimum_balance_to_keep"])
    if cents(profile["current_available_balance"]) < floor:
        return 0, None  # opening cash already breaches the reserve
    suffix = [0] * len(values)
    low = values[-1]
    for i in reversed(range(len(values))):
        low = min(low, values[i])
        suffix[i] = low - floor
    safe = max(0, min(requested, suffix[0]))
    earliest = next(
        (
            i
            for i, amount in enumerate(suffix)
            if amount >= requested and min(values[:i] or [floor]) >= floor
        ),
        None,
    )
    return safe, earliest

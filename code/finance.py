"""Conservative recurrence inference and a fixed 90-day cash timeline."""

import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from evidence import payroll_facts
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


def forecast(dataset, request, estimator="mean"):
    profile = dataset.profiles[request["user_id"]]
    start = date.fromisoformat(request["request_date"])
    end = start + timedelta(days=90)
    home = profile["home_currency"]
    events = dataset.resolved_events(request)
    facts = payroll_facts(dataset.messages[request["user_id"]], request)
    flows, streams, notes = [], [], []
    groups = defaultdict(list)
    histories = []
    successors = {
        e["linked_event_id"]: e
        for e in events
        if e["linked_event_id"] and e["status"] in ("settled", "scheduled")
    }
    seen = set()
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
        ):
            continue
        fingerprint = (
            e["description"],
            e["direction"],
            e["amount"],
            e["currency"],
            e["settlement_date"],
            e["status"],
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
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
        values = [
            fx(
                dataset,
                e["amount"],
                e["currency"],
                home,
                date.fromisoformat(e["settlement_date"]),
            )
            for e in group[-3:]
        ]
        amount = (
            max(values)
            if estimator == "max"
            else cents(Decimal(sum(values)) / (len(values) * 100))
        )
        e = group[-1]
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
    # seasonal earnings and irregular freelance/platform payouts.
    regular = [
        e
        for e in histories
        if e["description"]
        in {
            "Payroll credit",
            "Base salary",
            "Primary household salary",
            "First-job payroll",
            "New employer payroll",
            "International employer payroll",
            "Payroll after returning from leave",
            "Next confirmed salary",
        }
    ]
    regular.sort(key=lambda e: e["settlement_date"])
    ended = facts.get("ended") or any(
        e["description"] == "Final employer payroll" for e in histories
    )
    if not ended and (regular or facts.get("amount")):
        last = regular[-1] if regular else None
        amount = facts.get("amount", last["amount"] if last else None)
        currency = facts.get("currency", last["currency"] if last else home)
        if "date" in facts:
            first = date.fromisoformat(facts["date"])
        elif last:
            first = date.fromisoformat(last["settlement_date"])
            while first < start:
                first = month_date(first, 1)
        else:
            first = start.replace(day=15)
            if first < start:
                first = month_date(first, 1)
        if amount:
            for n in range(5):
                day = month_date(first, n)
                if start <= day <= end:
                    value = fx(dataset, amount, currency, home, day)
                    flows.append(
                        Cash(
                            day,
                            value,
                            facts.get("source", last["event_id"] if last else "salary"),
                            "Confirmed recurring salary",
                        )
                    )
                    if n == 0 and facts.get("arrears"):
                        flows.append(
                            Cash(
                                day,
                                fx(dataset, facts["arrears"], currency, home, day),
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

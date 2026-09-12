"""Exact monetary arithmetic and small immutable financial records."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def money(value):
    return format(Decimal(value) / 100, ".2f").rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Cash:
    day: date
    amount: int
    event_id: str
    description: str


@dataclass(frozen=True)
class Stream:
    event_id: str
    category: str
    description: str
    amount: int
    dates: tuple
    flexibility: str
    minimum: int


@dataclass(frozen=True)
class Plan:
    method: str
    payments: tuple
    changes: tuple = ()
    option_id: str = ""
    cost: int = 0

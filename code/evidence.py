"""Read-only evidence resolution; untrusted text never becomes instructions."""

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def index(rows, field):
    result = defaultdict(list)
    for row in rows:
        result[row[field]].append(row)
    return result


class Dataset:
    def __init__(self, root):
        self.root = Path(root)
        self.profiles = {
            r["user_id"]: r for r in read_csv(self.root / "financial_profiles.csv")
        }
        self.events = index(read_csv(self.root / "financial_events.csv"), "user_id")
        self.messages = index(read_csv(self.root / "messages.csv"), "user_id")
        self.images = {
            r["related_event_id"]: r for r in read_csv(self.root / "images.csv")
        }
        self.options = index(
            read_csv(self.root / "request_payment_options.csv"), "request_id"
        )
        self.rates = {
            (r["rate_date"], r["from_currency"], r["to_currency"]): r["rate"]
            for r in read_csv(self.root / "exchange_rates.csv")
        }
        self.image_facts = json.loads(
            Path(__file__).with_name("image_facts.json").read_text()
        )

    def resolved_events(self, request):
        out = []
        for source in self.events[request["user_id"]]:
            e = dict(source)
            if e["event_id"] in self.images:
                image_id = self.images[e["event_id"]]["image_id"]
                path = self.root / "media" / "images" / (image_id + ".png")
                if not path.is_file():
                    raise ValueError(f"Missing evidence image: {path}")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                fact = self.image_facts.get(digest)
                if fact is None:
                    raise ValueError(
                        f"Unreviewed image {image_id}; extract and verify before running"
                    )
                e["amount"] = fact["amount"]
                e["currency"] = fact["currency"]
                e["_image"] = image_id
                if (
                    fact.get("overdue_amount")
                    and request["request_date"] > fact["due_date"]
                ):
                    e["amount"] = fact["overdue_amount"]
            if not e["amount"]:
                raise ValueError(f"Unresolved amount: {e['event_id']}")
            out.append(e)
        return out


def payroll_facts(messages, request):
    """Recognize explicit payroll facts in the supplied English/Indonesian messages.

    Values are extracted from currency-labelled clauses, never arbitrary numbers.
    A limited grammar intentionally ignores payout promotions and embedded commands.
    """
    facts = {}
    for m in sorted(messages, key=lambda x: (x["sent_at"], x["message_id"])):
        if m["sent_at"][:10] > request["request_date"]:
            continue
        if m["request_id"] and m["request_id"] != request["request_id"]:
            continue
        text = m["message_text"]
        low = text.lower()
        amounts = re.findall(r"\b(INR|ZAR|IDR|USD|EUR)\s+([\d,]+(?:\.\d+)?)", text)
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
        if "rent by" in low:
            pct = re.search(r"rent by (\d+(?:\.\d+)?)%", low)
            if pct:
                facts["rent_increase"] = pct[1]
        if m["source_type"] == "employer":
            if any(
                s in low
                for s in [
                    "your employment has ended",
                    "hubungan kerja anda telah berakhir",
                    "seasonal contract has ended",
                    "kontrak musiman saat ini telah berakhir",
                ]
            ):
                facts["ended"] = True
            if amounts:
                facts["currency"], facts["amount"] = (
                    amounts[0][0],
                    amounts[0][1].replace(",", ""),
                )
                facts["source"] = m["message_id"]
                facts["ended"] = False
                if dates:
                    facts["date"] = dates[0]
                # Arrears are explicitly non-recurring. Do not turn a prior
                # arrears payment into future income without a future date.
                if len(amounts) > 1 and any(
                    s in low for s in ["one-time arrears", "tunggakan satu kali"]
                ):
                    facts["arrears"] = amounts[1][1].replace(",", "")
            if dates and any(
                s in low
                for s in [
                    "salary is now expected on",
                    "gaji yang sudah dikonfirmasi kini diperkirakan",
                ]
            ):
                facts["date"] = dates[0]
        if (
            m["source_type"] == "service_provider"
            and amounts
            and dates
            and any(
                s in low
                for s in ["approved an invoice payment", "menyetujui pembayaran faktur"]
            )
        ):
            facts["invoice"] = (
                amounts[0][0],
                amounts[0][1].replace(",", ""),
                dates[0],
                m["message_id"],
            )
    return facts

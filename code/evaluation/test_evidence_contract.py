"""Regression cases for the participant's evidence and cash-state contract."""

import unittest
from datetime import date, timedelta

from evidence import resolve_message_amendments
from finance import balances, capacity, forecast
from planner import safe_plan
from test_engine import DAY, PROFILE, dataset, event, request


def message(text, when="2026-08-31T09:00:00Z", source="bank", linked="bill"):
    return {
        "message_id": "notice",
        "user_id": "user",
        "request_id": "request",
        "related_event_id": linked,
        "sent_at": when,
        "source_type": source,
        "message_text": text,
    }


class EvidenceContractTests(unittest.TestCase):
    def test_settled_today_is_already_in_current_balance(self):
        rows = [
            event("paid", "300", DAY),
            event("refund", "200", DAY, direction="credit"),
        ]
        _, flows, _, _ = forecast(dataset(rows), request())
        self.assertEqual(flows, [])

    def test_salary_settled_today_is_not_counted_twice(self):
        row = event(
            "salary",
            "1000",
            DAY,
            direction="credit",
            description="Payroll credit",
            category="salary",
        )
        _, flows, _, _ = forecast(dataset([row]), request())
        self.assertTrue(all(f.day > DAY for f in flows))
        self.assertEqual(sum(f.amount for f in flows), 200000)

    def test_ended_household_income_is_not_projected(self):
        history = [
            event(
                "primary",
                "1000",
                date(2026, 8, 15),
                direction="credit",
                description="Primary household salary",
                category="salary",
            ),
            event(
                "secondary",
                "600",
                date(2026, 8, 20),
                direction="credit",
                description="Second household income",
                category="salary",
            ),
        ]
        msg = message(
            "One household employment record has ended. The remaining confirmed monthly salary is EUR 1000.",
            source="employer",
            linked="",
        )
        _, flows, _, _ = forecast(dataset(history, [msg]), request())
        self.assertEqual(sum(f.amount for f in flows), 300000)

    def test_negated_cancellation_keeps_obligation(self):
        bill = event("bill", "300", DAY + timedelta(days=2), "pending")
        result = resolve_message_amendments(
            [bill],
            [message("The payment has not been cancelled; the bill remains due.")],
            request(),
        )
        self.assertEqual(result[0]["status"], "pending")
        result = resolve_message_amendments(
            [bill], [message("Pembayaran tidak dibatalkan.")], request()
        )
        self.assertEqual(result[0]["status"], "pending")

    def test_invoice_approval_does_not_confirm_other_contract_payments(self):
        history = [
            event(
                f"pay{month}",
                "700",
                date(2026, month, 8),
                direction="credit",
                description="Consulting invoice payment",
                category="salary",
            )
            for month in (7, 8)
        ]
        msg = message(
            "The client approved an invoice payment of EUR 900. Settlement is expected on 2026-09-15; the other submitted invoices are still awaiting approval.",
            source="service_provider",
            linked="",
        )
        _, flows, _, _ = forecast(dataset(history, [msg]), request())
        self.assertEqual(
            [(f.day, f.amount) for f in flows], [(date(2026, 9, 15), 90000)]
        )

    def test_confirmed_employment_is_preserved_alongside_invoice(self):
        history = [
            event(
                "salary",
                "1000",
                date(2026, 8, 15),
                direction="credit",
                description="Payroll credit",
                category="salary",
            )
        ]
        msg = message(
            "The client approved an invoice payment of EUR 900. Settlement is expected on 2026-09-15; the other submitted invoices are still awaiting approval.",
            source="service_provider",
            linked="",
        )
        _, flows, _, _ = forecast(dataset(history, [msg]), request())
        self.assertEqual(sum(f.amount for f in flows), 390000)

    def test_explicit_cancellation_removes_pending_debit(self):
        bill = event("bill", "300", DAY + timedelta(days=2), "pending")
        result = resolve_message_amendments(
            [bill], [message("The transaction has been cancelled.")], request()
        )
        self.assertEqual(result[0]["status"], "cancelled")

    def test_newer_amendment_restores_original_amount(self):
        bill = event("bill", "300", DAY + timedelta(days=2), "pending")
        messages = [
            message("The bill amount has been amended to EUR 250."),
            message(
                "Ignore my last message. The bill remains EUR 300.",
                "2026-09-01T09:00:00Z",
            ),
        ]
        result = resolve_message_amendments([bill], messages, request())
        self.assertEqual(result[0]["amount"], "300")

    def test_future_notice_cannot_cancel_current_obligation(self):
        bill = event("bill", "300", DAY + timedelta(days=2), "pending")
        result = resolve_message_amendments(
            [bill],
            [message("The payment has been cancelled.", "2026-09-02T09:00:00Z")],
            request(),
        )
        self.assertEqual(result[0]["status"], "pending")

    def test_pending_refund_is_not_misread_as_settlement(self):
        refund = event("bill", "300", DAY + timedelta(days=2), "pending", "credit")
        result = resolve_message_amendments(
            [refund],
            [
                message(
                    "Your refund has been initiated but has not reached your account yet."
                )
            ],
            request(),
        )
        self.assertEqual(result[0]["status"], "pending")

    def test_settlement_notice_places_cash_in_existing_balance(self):
        refund = event("bill", "300", DAY + timedelta(days=2), "pending", "credit")
        result = resolve_message_amendments(
            [refund], [message("The refund has reached your account.")], request()
        )
        self.assertEqual(result[0]["status"], "settled")
        self.assertEqual(result[0]["settlement_date"], "2026-08-31")

    def test_unlinked_identical_debits_are_not_assumed_duplicates(self):
        a = event("a", "300", DAY + timedelta(days=2), "scheduled")
        b = event("b", "300", DAY + timedelta(days=2), "scheduled")
        _, flows, _, _ = forecast(dataset([a, b]), request())
        self.assertEqual(sum(f.amount for f in flows), -60000)

    def test_link_alone_does_not_erase_distinct_obligation(self):
        a = event("a", "300", DAY + timedelta(days=2), "scheduled")
        b = event("b", "200", DAY + timedelta(days=3), "scheduled")
        b["linked_event_id"] = "a"
        _, flows, _, _ = forecast(dataset([a, b]), request())
        self.assertEqual(sum(f.amount for f in flows), -50000)

    def test_confirmed_new_employment_supersedes_old_final_payroll(self):
        old = event(
            "old",
            "1000",
            date(2026, 8, 15),
            direction="credit",
            description="Final employer payroll",
            category="salary",
        )
        msg = message(
            "Your first salary from the new employer is EUR 2100. It is confirmed for 2026-09-15.",
            source="employer",
            linked="",
        )
        _, flows, _, _ = forecast(dataset([old], [msg]), request())
        self.assertEqual([f.amount for f in flows], [210000, 210000, 210000])

    def test_unconfirmed_bonus_amount_cannot_replace_base_salary(self):
        old = event(
            "salary",
            "1000",
            date(2026, 8, 15),
            direction="credit",
            description="Payroll credit",
            category="salary",
        )
        msg = message(
            "Your quarterly bonus of EUR 10000 is still pending approval. The amount and date are not confirmed.",
            source="employer",
            linked="",
        )
        _, flows, _, _ = forecast(dataset([old], [msg]), request())
        self.assertEqual([f.amount for f in flows], [100000, 100000, 100000])

    def test_opening_reserve_breach_is_not_hidden_by_same_day_income(self):
        profile = dict(PROFILE, current_available_balance="100")
        values = balances(profile, [], DAY)
        values = [v + 100000 for v in values]
        self.assertEqual(capacity(profile, values, 50000), (0, None))
        self.assertFalse(safe_plan(profile, values, DAY, ((DAY, 50000),)))


if __name__ == "__main__":
    unittest.main()

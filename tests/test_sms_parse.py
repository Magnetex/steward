"""Parsers checked against real message text.

Every ``body`` below is a message the user actually received (figures
redacted). If a bank changes its wording, the failure belongs here.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services import sms_parse as sp


D = Decimal

HDFC_SALARY = (
    "Update! INR 1,07,586.00 deposited in HDFC Bank A/c XX4458 on 29-JUL-26 for "
    "NEFT Cr-ICIC0000104-ULTRAVIOLET  SAL JULY 26-JOEL CHRISTIAN-INXXXXXXXXXX8016."
    "Avl bal INR 1,58,875.65. Cheque deposits in A/C are subject to clearing"
)
HDFC_UPI_CREDIT = (
    "Credit Alert! Rs.2348.00 credited to HDFC Bank A/c XX4458 on 29-07-26 from "
    "VPA 8332906887@superyes (UPI 621065532276)"
)
HDFC_NEFT_DEBIT = (
    "UPDATE: INR 17,000.00 debited from HDFC Bank XX4458 on 01-AUG-26. Info: "
    "NEFT Dr-IOBA0001302-SURESH BABU K-SANDOZ - MUM-HDFCH01162085499-NET BANKING "
    "SI -Rent. Avl bal:INR 94,246.65"
)
HDFC_CARD = (
    "Spent Rs.555 From HDFC Bank Card x8876 At BHATTA S FOODS PRIVATE On "
    "2026-07-26:22:01:27 Bal Rs.51603.32 Not You? Call 18002586161/SMS BLOCK DC "
    " 8876 to 7308080808"
)
HDFC_UPI_SENT = (
    "Sent Rs.738.00\nFrom HDFC Bank A/C *4458\nTo Swiggy Limited\nOn 01/08/26\n"
    "Ref 127216477129\nNot You?\nCall 18002586161/SMS BLOCK UPI to 7308080808"
)
PLUXEE_TOPUP = (
    "Your Pluxee Card has been successfully credited with Rs.2700 towards  Meal "
    "Wallet on Thu Jul 30 2026 11:44:28. Your current Meal Wallet balance is Rs.6815.55."
)
PLUXEE_REVERSAL = (
    "Your Pluxee Card xx7803 has been credited with INR 1347.48 on Sun Jul 26 2026 "
    "21:53:49as a reversal against a previous transaction on Jul 26,2026 21:47:58."
)
PLUXEE_SPEND = (
    "Rs. 1347.48 spent from Pluxee  Meal wallet, card no.xx7803 on 26-07-2026 "
    "21:47:58 at ETERNAL LIM . Avl bal Rs.2768.07. Not you call 18002106919"
)
PLUXEE_FEE = (
    "Rs. 2.00 deducted from your Pluxee Card xxxx7803 towards ONLINE CONVENIENCE FEE. Pluxee"
)
RNSB_SI_DEBIT = (
    "Your RNSB A/C No. 053-XXXX7655 is Debited for Rs.15000.00 towards TRANSFER SI "
    " on 26/07/2026 , 22:52:18 & Available Bal is Rs. 29380.81"
)
RNSB_IMPS_OUT = (
    "Your a/c no. XXXXXXXX7655 is debited for Rs.38000.00 /- on 24-07-26 and a/c "
    "XXXXXXX458 credited (IMPS Ref no 620517586439). Call 9428294282/SMS BLOCK ACCT "
    "<Last5DigitAccNo> to 7030930362, If you have not done this transaction.-RNSB Bank."
)
RNSB_CREDIT = (
    "Your a/c no. XXXXXXXX7655 is credited by Rs.15000.00 on 06-07-26 (IMPS Ref no "
    "618717386944).Call 9428294282 If you have not done this transaction.-RNSB Bank."
)


@pytest.mark.parametrize("sender, body, direction, amount, acct, when", [
    ("VM-HDFCBK", HDFC_SALARY,     "credit", D("107586.00"), "4458", date(2026, 7, 29)),
    ("AD-HDFCBK", HDFC_UPI_CREDIT, "credit", D("2348.00"),   "4458", date(2026, 7, 29)),
    ("VM-HDFCBK", HDFC_NEFT_DEBIT, "debit",  D("17000.00"),  "4458", date(2026, 8, 1)),
    ("VM-HDFCBK", HDFC_CARD,       "debit",  D("555"),       "8876", date(2026, 7, 26)),
    ("VM-HDFCBK", HDFC_UPI_SENT,   "debit",  D("738.00"),    "4458", date(2026, 8, 1)),
    ("AX-PLUXEE", PLUXEE_SPEND,    "debit",  D("1347.48"),   "7803", date(2026, 7, 26)),
    ("AX-PLUXEE", PLUXEE_REVERSAL, "credit", D("1347.48"),   "7803", date(2026, 7, 26)),
    ("AX-PLUXEE", PLUXEE_TOPUP,    "credit", D("2700"),      "",     date(2026, 7, 30)),
    ("VM-RNSBNK", RNSB_SI_DEBIT,   "debit",  D("15000.00"),  "7655", date(2026, 7, 26)),
    ("VM-RNSBNK", RNSB_IMPS_OUT,   "debit",  D("38000.00"),  "7655", date(2026, 7, 24)),
    ("VM-RNSBNK", RNSB_CREDIT,     "credit", D("15000.00"),  "7655", date(2026, 7, 6)),
])
def test_parses_real_messages(sender, body, direction, amount, acct, when):
    r = sp.parse(sender, body)
    assert r is not None, "message did not parse at all"
    assert r.direction == direction
    assert r.amount == amount
    assert r.account_hint == acct
    assert r.txn_date == when


def test_never_mistakes_the_balance_for_the_amount():
    """Most alerts also state a balance, usually a larger number."""
    r = sp.parse("VM-HDFCBK", HDFC_SALARY)
    assert r.amount == D("107586.00")
    assert r.balance == D("158875.65")

    r = sp.parse("VM-HDFCBK", HDFC_CARD)
    assert r.amount == D("555"), "grabbed the Rs.51603.32 balance"

    r = sp.parse("VM-RNSBNK", RNSB_SI_DEBIT)
    assert r.amount == D("15000.00"), "grabbed the Rs.29380.81 balance"


def test_extracts_useful_payees():
    assert sp.parse("VM-HDFCBK", HDFC_CARD).payee == "BHATTA S FOODS PRIVATE"
    assert sp.parse("VM-HDFCBK", HDFC_UPI_SENT).payee == "Swiggy Limited"
    assert sp.parse("AX-PLUXEE", PLUXEE_SPEND).payee == "ETERNAL LIM"
    assert "Rent" in sp.parse("VM-HDFCBK", HDFC_NEFT_DEBIT).payee


def test_self_transfer_carries_both_accounts():
    r = sp.parse("VM-RNSBNK", RNSB_IMPS_OUT)
    assert r.is_self_transfer_candidate
    assert r.account_hint == "7655"
    assert r.counterparty_hint == "458"
    assert r.reference == "620517586439"


def test_reversal_is_flagged_not_treated_as_income():
    assert sp.parse("AX-PLUXEE", PLUXEE_REVERSAL).is_reversal
    assert not sp.parse("AX-PLUXEE", PLUXEE_TOPUP).is_reversal


def test_message_without_a_date_parses_with_none():
    """The convenience fee carries no date; the caller substitutes the SMS time."""
    r = sp.parse("AX-PLUXEE", PLUXEE_FEE)
    assert r.amount == D("2.00")
    assert r.txn_date is None
    assert r.payee == "ONLINE CONVENIENCE FEE"


@pytest.mark.parametrize("sender, body", [
    ("DM-AMAZON", "Your order has shipped, Rs.500 off your next purchase!"),
    ("VM-HDFCBK", "Dear Customer, your KYC is pending. Visit your branch."),
    ("AX-PLUXEE", "Wishing you a happy new year from Pluxee!"),
    ("VM-HDFCBK", ""),
])
def test_ignores_messages_that_are_not_transactions(sender, body):
    assert sp.parse(sender, body) is None


def test_only_known_senders_are_considered():
    assert sp.is_known_sender("VM-HDFCBK")
    assert sp.is_known_sender("JD-PLUXEE-S")
    assert sp.is_known_sender("VK-RNSBNK")
    assert not sp.is_known_sender("DM-AMAZON")
    assert not sp.is_known_sender("MOM")


@pytest.mark.parametrize("raw, expected", [
    ("1,07,586.00", D("107586.00")),
    ("555", D("555")),
    ("2,348.00", D("2348.00")),
    ("", None),
    ("abc", None),
])
def test_amount_normalisation(raw, expected):
    assert sp.parse_amount(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("29-JUL-26", date(2026, 7, 29)),
    ("29-07-26", date(2026, 7, 29)),
    ("26-07-2026", date(2026, 7, 26)),
    ("01/08/26", date(2026, 8, 1)),
    ("26/07/2026", date(2026, 7, 26)),
    ("2026-07-26", date(2026, 7, 26)),
    ("Thu Jul 30 2026", date(2026, 7, 30)),
    ("nonsense", None),
])
def test_date_normalisation(raw, expected):
    assert sp.parse_date(raw) == expected

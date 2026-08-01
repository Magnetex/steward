"""Parse bank alert SMS into structured transaction candidates.

Deliberately free of any Termux or database dependency: everything here takes
plain strings and returns plain data, so the patterns can be tested against
real message text on any machine.

Two things make bank SMS harder than they look:

* **Most messages contain two amounts.** "Avl bal INR 1,58,875.65" is usually
  larger than the transaction itself, so every pattern anchors on the
  transaction amount specifically rather than scanning for a rupee figure.
* **Dates come in eight shapes** across the banks (and one message type has no
  date at all), so ``parse_date`` tries a list of formats and the caller falls
  back to the SMS's own received timestamp.

Add a bank by writing patterns and appending to ``PARSERS``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# --- amounts ---------------------------------------------------------------
# Indian grouping (1,07,586.00), optional decimals, optional space after the
# currency marker, optional trailing "/-".
_AMOUNT = r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)"


def parse_amount(raw: str) -> Decimal | None:
    """'1,07,586.00' -> Decimal('107586.00'). None if it isn't a number."""
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


# --- dates -----------------------------------------------------------------
# Ordered by specificity; the first that parses wins.
_DATE_FORMATS = [
    "%d-%b-%y",           # 29-JUL-26
    "%d-%m-%y",           # 29-07-26
    "%d-%m-%Y",           # 26-07-2026
    "%d/%m/%y",           # 01/08/26
    "%d/%m/%Y",           # 26/07/2026
    "%Y-%m-%d",           # 2026-07-26
    "%b %d %Y",           # Jul 30 2026
]


def parse_date(raw: str) -> date | None:
    """Parse any of the bank date shapes. None if unrecognised."""
    if not raw:
        return None
    cleaned = raw.strip().rstrip(",").strip()
    # Drop a leading weekday name ("Thu Jul 30 2026") and any trailing time.
    cleaned = re.sub(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+", "", cleaned, flags=re.I)
    cleaned = re.split(r"[:\s,]+(?=\d{1,2}:\d{2})", cleaned)[0].strip()
    cleaned = cleaned.rstrip(":").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# --- result ----------------------------------------------------------------
@dataclass
class ParsedSMS:
    """One transaction candidate extracted from a message."""
    direction: str                     # "debit" | "credit"
    amount: Decimal
    bank: str                          # hdfc | pluxee | rnsb
    account_hint: str = ""             # trailing digits, e.g. "4458"
    counterparty_hint: str = ""        # the *other* account, for self-transfers
    payee: str = ""
    txn_date: date | None = None       # None -> caller uses the SMS timestamp
    balance: Decimal | None = None     # bank's stated balance, for reconciliation
    reference: str = ""
    is_reversal: bool = False          # a refund, not fresh income

    @property
    def is_self_transfer_candidate(self) -> bool:
        return bool(self.counterparty_hint)


def _clean_payee(raw: str) -> str:
    """Tidy a merchant/counterparty fragment for display."""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", raw).strip(" .,-")
    # Drop the trailing noise banks append after the useful part.
    text = re.split(r"\s+(?:Not You|Call \d|Avl bal|Bal )", text, flags=re.I)[0]
    return text.strip(" .,-")[:120]


# --- HDFC ------------------------------------------------------------------
def _hdfc(body: str) -> ParsedSMS | None:
    # "Spent Rs.555 From HDFC Bank Card x8876 At MERCHANT On 2026-07-26:22:01:27 Bal Rs.51603.32"
    m = re.search(
        rf"Spent\s+{_AMOUNT}\s+From\s+HDFC\s+Bank\s+Card\s+x*(\d+)\s+At\s+(.+?)\s+On\s+"
        r"(\d{4}-\d{2}-\d{2})", body, re.I | re.S)
    if m:
        bal = re.search(rf"Bal\s+{_AMOUNT}", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(1)), bank="hdfc",
            account_hint=m.group(2), payee=_clean_payee(m.group(3)),
            txn_date=parse_date(m.group(4)),
            balance=parse_amount(bal.group(1)) if bal else None)

    # Multi-line UPI: "Sent Rs.738.00 / From HDFC Bank A/C *4458 / To Swiggy Limited / On 01/08/26"
    m = re.search(
        rf"Sent\s+{_AMOUNT}\s+From\s+HDFC\s+Bank\s+A/C\s+[*x]*(\d+)\s+To\s+(.+?)\s+On\s+"
        r"([\d/\-]+)", body, re.I | re.S)
    if m:
        ref = re.search(r"Ref\s+(\w+)", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(1)), bank="hdfc",
            account_hint=m.group(2), payee=_clean_payee(m.group(3)),
            txn_date=parse_date(m.group(4)),
            reference=ref.group(1) if ref else "")

    # "INR 17,000.00 debited from HDFC Bank XX4458 on 01-AUG-26. Info: NEFT Dr-...-Rent"
    m = re.search(
        rf"{_AMOUNT}\s+debited\s+from\s+HDFC\s+Bank\s+(?:A/c\s+)?[Xx*]*(\d+)\s+on\s+"
        r"([\w\-/]+)", body, re.I)
    if m:
        info = re.search(r"Info:\s*(.+?)(?:\.\s*Avl|$)", body, re.I | re.S)
        bal = re.search(rf"Avl bal:?\s*{_AMOUNT}", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(1)), bank="hdfc",
            account_hint=m.group(2), txn_date=parse_date(m.group(3)),
            payee=_clean_payee(info.group(1)) if info else "",
            balance=parse_amount(bal.group(1)) if bal else None)

    # "Rs.2348.00 credited to HDFC Bank A/c XX4458 on 29-07-26 from VPA x@y (UPI 62106…)"
    m = re.search(
        rf"{_AMOUNT}\s+credited\s+to\s+HDFC\s+Bank\s+A/c\s+[Xx*]*(\d+)\s+on\s+([\w\-/]+)",
        body, re.I)
    if m:
        src = re.search(r"from\s+VPA\s+(\S+)", body, re.I)
        ref = re.search(r"\(UPI\s+(\w+)\)", body, re.I)
        return ParsedSMS(
            direction="credit", amount=parse_amount(m.group(1)), bank="hdfc",
            account_hint=m.group(2), txn_date=parse_date(m.group(3)),
            payee=_clean_payee(src.group(1)) if src else "",
            reference=ref.group(1) if ref else "")

    # "INR 1,07,586.00 deposited in HDFC Bank A/c XX4458 on 29-JUL-26 for NEFT Cr-…"
    m = re.search(
        rf"{_AMOUNT}\s+deposited\s+in\s+HDFC\s+Bank\s+A/c\s+[Xx*]*(\d+)\s+on\s+([\w\-/]+)",
        body, re.I)
    if m:
        info = re.search(r"\bfor\s+(.+?)(?:\.?Avl bal|$)", body, re.I | re.S)
        bal = re.search(rf"Avl bal:?\s*{_AMOUNT}", body, re.I)
        return ParsedSMS(
            direction="credit", amount=parse_amount(m.group(1)), bank="hdfc",
            account_hint=m.group(2), txn_date=parse_date(m.group(3)),
            payee=_clean_payee(info.group(1)) if info else "",
            balance=parse_amount(bal.group(1)) if bal else None)
    return None


# --- Pluxee ----------------------------------------------------------------
def _pluxee(body: str) -> ParsedSMS | None:
    # "Rs. 1347.48 spent from Pluxee Meal wallet, card no.xx7803 on 26-07-2026 21:47:58 at MERCHANT"
    m = re.search(
        rf"{_AMOUNT}\s+spent\s+from\s+Pluxee.*?card\s+no\.?\s*x*(\d+)\s+on\s+"
        r"([\d\-/]+)(?:\s+[\d:]+)?\s+at\s+(.+?)(?:\.\s*Avl|$)", body, re.I | re.S)
    if m:
        bal = re.search(rf"Avl bal\s+{_AMOUNT}", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(1)), bank="pluxee",
            account_hint=m.group(2), txn_date=parse_date(m.group(3)),
            payee=_clean_payee(m.group(4)),
            balance=parse_amount(bal.group(1)) if bal else None)

    # "Rs. 2.00 deducted from your Pluxee Card xxxx7803 towards ONLINE CONVENIENCE FEE."
    # No date in this one at all -- the caller falls back to the SMS timestamp.
    m = re.search(
        rf"{_AMOUNT}\s+deducted\s+from\s+your\s+Pluxee\s+Card\s+x*(\d+)\s+towards\s+(.+?)(?:\.|$)",
        body, re.I | re.S)
    if m:
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(1)), bank="pluxee",
            account_hint=m.group(2), payee=_clean_payee(m.group(3)))

    # "Your Pluxee Card xx7803 has been credited with INR 1347.48 on Sun Jul 26 2026 21:53:49as a reversal…"
    # Note the missing space before "as" -- hence the non-greedy time match.
    m = re.search(
        rf"Pluxee\s+Card\s+x*(\d+)\s+has\s+been\s+credited\s+with\s+{_AMOUNT}\s+on\s+"
        r"((?:\w{3}\s+)?\w{3}\s+\d{1,2}\s+\d{4})", body, re.I | re.S)
    if m:
        return ParsedSMS(
            direction="credit", amount=parse_amount(m.group(2)), bank="pluxee",
            account_hint=m.group(1), txn_date=parse_date(m.group(3)),
            payee="Reversal" if re.search(r"reversal", body, re.I) else "Pluxee credit",
            is_reversal=bool(re.search(r"reversal", body, re.I)))

    # "Your Pluxee Card has been successfully credited with Rs.2700 towards Meal Wallet on Thu Jul 30 2026…"
    # No card number in this variant.
    m = re.search(
        rf"Pluxee\s+Card\s+has\s+been\s+successfully\s+credited\s+with\s+{_AMOUNT}\s+towards\s+"
        r"(.+?)\s+on\s+((?:\w{3}\s+)?\w{3}\s+\d{1,2}\s+\d{4})", body, re.I | re.S)
    if m:
        return ParsedSMS(
            direction="credit", amount=parse_amount(m.group(1)), bank="pluxee",
            txn_date=parse_date(m.group(3)),
            payee=_clean_payee(m.group(2)) or "Pluxee top-up")
    return None


# --- RNSB ------------------------------------------------------------------
def _rnsb(body: str) -> ParsedSMS | None:
    # Self-transfer: "a/c no. XXXXXXXX7655 is debited for Rs.38000.00 /- on 24-07-26
    #                 and a/c XXXXXXX458 credited (IMPS Ref no 620517586439)"
    m = re.search(
        rf"a/c\s+no\.?\s*[X*]*(\d+)\s+is\s+debited\s+for\s+{_AMOUNT}\s*(?:/-)?\s*on\s+([\w\-/]+)"
        r"\s+and\s+a/c\s+[X*]*(\d+)\s+credited", body, re.I | re.S)
    if m:
        ref = re.search(r"IMPS Ref no\s+(\w+)", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(2)), bank="rnsb",
            account_hint=m.group(1), counterparty_hint=m.group(4),
            txn_date=parse_date(m.group(3)),
            reference=ref.group(1) if ref else "", payee="Transfer")

    # "RNSB A/C No. 053-XXXX7655 is Debited for Rs.15000.00 towards TRANSFER SI on 26/07/2026"
    m = re.search(
        rf"A/C\s+No\.?\s*[\d\-]*[X*]*(\d+)\s+is\s+Debited\s+for\s+{_AMOUNT}\s*(?:/-)?"
        r"(?:\s+towards\s+(.+?))?\s+on\s+([\d/\-]+)", body, re.I | re.S)
    if m:
        bal = re.search(rf"Available Bal is\s+{_AMOUNT}", body, re.I)
        return ParsedSMS(
            direction="debit", amount=parse_amount(m.group(2)), bank="rnsb",
            account_hint=m.group(1), txn_date=parse_date(m.group(4)),
            payee=_clean_payee(m.group(3) or ""),
            balance=parse_amount(bal.group(1)) if bal else None)

    # "a/c no. XXXXXXXX7655 is credited by Rs.15000.00 on 06-07-26 (IMPS Ref no …)"
    m = re.search(
        rf"a/c\s+no\.?\s*[X*]*(\d+)\s+is\s+credited\s+by\s+{_AMOUNT}\s*(?:/-)?\s*on\s+([\w\-/]+)",
        body, re.I | re.S)
    if m:
        ref = re.search(r"IMPS Ref no\s+(\w+)", body, re.I)
        return ParsedSMS(
            direction="credit", amount=parse_amount(m.group(2)), bank="rnsb",
            account_hint=m.group(1), txn_date=parse_date(m.group(3)),
            reference=ref.group(1) if ref else "")
    return None


# Sender IDs vary by message type (VM-HDFCBK, AD-HDFCBK, …), so match on the
# bank name appearing anywhere in the sender rather than an exact string.
PARSERS: list[tuple[str, str, callable]] = [
    ("hdfc", r"HDFC", _hdfc),
    ("pluxee", r"PLUXEE|SODEXO", _pluxee),
    ("rnsb", r"RNSB", _rnsb),
]


def is_known_sender(sender: str) -> bool:
    return any(re.search(pat, sender or "", re.I) for _, pat, _ in PARSERS)


def parse(sender: str, body: str) -> ParsedSMS | None:
    """Parse one message. None when the sender is unknown or nothing matched.

    Returning None is normal and safe -- an unrecognised message is simply not
    imported, rather than guessed at.
    """
    if not body:
        return None
    for _, pattern, parser in PARSERS:
        if re.search(pattern, sender or "", re.I):
            result = parser(body)
            if result and result.amount and result.amount > 0:
                return result
    return None

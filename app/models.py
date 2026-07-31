"""SQLAlchemy models for Build Steward.

Money & quantities use :class:`app.money.DecimalText` (exact Decimal <-> TEXT).
Dates are plain calendar dates in IST; ``created_at`` timestamps are naive IST.
Balances, spent amounts and holding units are always *computed from
transactions* — never stored — per the spec. Cheap convenience properties live
here; batch aggregations live in ``app.services``.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .extensions import db
from .money import DecimalText, ZERO
from .timeutil import now_ist

# ---------------------------------------------------------------------------
# Enumerated string values (kept as plain constants — SQLite has no enums)
# ---------------------------------------------------------------------------
ACCOUNT_TYPES = ["savings_bank", "wallet", "cash"]
CASH_LIKE_TYPES = ["savings_bank", "wallet", "cash"]  # count as "available"
# Sinking-fund goals earmark slices of these existing assets (+ cash), rather
# than holding money of their own.
FUND_SOURCE_KINDS = ["mf", "gold", "deposit", "stock", "cash"]
CATEGORY_KINDS = ["income", "expense", "savings"]
TXN_TYPES = ["income", "expense", "transfer", "savings"]
INVEST_KINDS = ["mf", "gold", "deposit", "epf", "stock"]
RECUR_FREQ = ["weekly", "monthly", "yearly"]
RECUR_MODES = ["auto_create", "remind_only"]
MF_TXN_TYPES = ["buy", "sip", "sell"]
DEPOSIT_KINDS = ["FD", "RD"]
GOLD_TXN_TYPES = ["buy", "sell"]
EPF_ENTRY_TYPES = ["contribution", "interest"]
ALERT_TYPES = ["overshoot", "recurring", "maturity", "reminder", "info"]


def _now():
    # store naive IST wall-clock time
    return now_ist().replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Accounts & categories
# ---------------------------------------------------------------------------
class Account(db.Model):
    __tablename__ = "account"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(20), nullable=False, default="savings_bank")
    opening_balance = db.Column(DecimalText, nullable=False, default=ZERO)
    icon = db.Column(db.String(16), default="🏦")
    color = db.Column(db.String(24), default="#1E6B4E")
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_now)

    @property
    def is_cash_like(self) -> bool:
        return self.type in CASH_LIKE_TYPES

    @property
    def balance(self) -> Decimal:
        """Convenience single-account balance (queries the DB)."""
        from .services.accounts import account_balance
        return account_balance(self.id)


class Category(db.Model):
    __tablename__ = "category"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    kind = db.Column(db.String(10), nullable=False, default="expense")
    icon = db.Column(db.String(16), default="🏷️")
    group = db.Column(db.String(40), default="")
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0)


# ---------------------------------------------------------------------------
# Transactions (+ splits)
# ---------------------------------------------------------------------------
class Transaction(db.Model):
    __tablename__ = "transaction"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(DecimalText, nullable=False, default=ZERO)
    type = db.Column(db.String(10), nullable=False, default="expense")

    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    transfer_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True, index=True)

    # Savings direction ("out" = cash -> savings, "in" = redeemed back to cash).
    # Only meaningful when type == "savings"; ignored otherwise.
    flow = db.Column(db.String(3), nullable=False, default="out")
    # Link back to the investment record this cash movement funds/redeems, so the
    # two stay in lockstep (created & deleted together). NULL for ordinary txns.
    invest_kind = db.Column(db.String(8), nullable=True)   # mf | gold | deposit | epf | stock
    invest_ref_id = db.Column(db.Integer, nullable=True)

    payee = db.Column(db.String(120), default="")
    note = db.Column(db.String(300), default="")
    tags = db.Column(db.String(200), default="")
    budget_month = db.Column(db.Date, nullable=False, index=True)

    # split support: a parent holds the total; children carry category+amount
    parent_id = db.Column(db.Integer, db.ForeignKey("transaction.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=_now)

    account = db.relationship("Account", foreign_keys=[account_id])
    transfer_account = db.relationship("Account", foreign_keys=[transfer_account_id])
    category = db.relationship("Category")
    splits = db.relationship(
        "Transaction",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        single_parent=True,
    )

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    @property
    def has_splits(self) -> bool:
        return bool(self.splits)

    @property
    def signed_amount(self) -> Decimal:
        """Effect on the account's balance: +income, -expense, 0 for transfers.

        Savings moves cash too: an "out" contribution leaves the account (-),
        an "in" redemption returns to it (+). The funded asset is valued in its
        own net-worth bucket, so cash out + bucket up nets to zero.
        """
        if self.type == "income":
            return self.amount
        if self.type == "expense":
            return -self.amount
        if self.type == "savings":
            return self.amount if self.flow == "in" else -self.amount
        return ZERO


class PayeeMemory(db.Model):
    __tablename__ = "payee_memory"
    id = db.Column(db.Integer, primary_key=True)
    payee = db.Column(db.String(120), unique=True, nullable=False, index=True)
    last_category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    last_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    last_type = db.Column(db.String(10), default="expense")
    uses = db.Column(db.Integer, default=1)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
class BudgetLine(db.Model):
    __tablename__ = "budget_line"
    id = db.Column(db.Integer, primary_key=True)
    budget_month = db.Column(db.Date, nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    planned_amount = db.Column(DecimalText, nullable=False, default=ZERO)
    category = db.relationship("Category")
    __table_args__ = (db.UniqueConstraint("budget_month", "category_id", name="uq_budget_month_cat"),)


# ---------------------------------------------------------------------------
# Recurring rules
# ---------------------------------------------------------------------------
class RecurringRule(db.Model):
    __tablename__ = "recurring_rule"
    id = db.Column(db.Integer, primary_key=True)
    payee = db.Column(db.String(120), default="")
    amount = db.Column(DecimalText, nullable=False, default=ZERO)
    type = db.Column(db.String(10), nullable=False, default="expense")
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    transfer_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)

    frequency = db.Column(db.String(10), nullable=False, default="monthly")
    day_of_month = db.Column(db.Integer, default=1)     # for monthly/yearly
    weekday = db.Column(db.Integer, default=0)          # 0=Mon, for weekly
    month_of_year = db.Column(db.Integer, default=1)    # for yearly
    next_due_date = db.Column(db.Date, nullable=False, index=True)

    mode = db.Column(db.String(12), nullable=False, default="auto_create")
    active = db.Column(db.Boolean, default=True, nullable=False)
    note = db.Column(db.String(300), default="")
    tags = db.Column(db.String(200), default="")
    # Set when a rule is auto-created to fund an investment (e.g. an RD's monthly
    # installment). Lets us retire the rule when that investment is removed.
    invest_kind = db.Column(db.String(8), nullable=True)   # mf | gold | deposit | epf | stock
    invest_ref_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_now)

    category = db.relationship("Category")
    account = db.relationship("Account", foreign_keys=[account_id])
    transfer_account = db.relationship("Account", foreign_keys=[transfer_account_id])


# ---------------------------------------------------------------------------
# Sinking funds
# ---------------------------------------------------------------------------
class SinkingFund(db.Model):
    """A savings goal. Holds no money of its own — it earmarks slices of existing
    assets (FD/RD/MF/gold/stock) or cash via :class:`FundAllocation` rows."""
    __tablename__ = "sinking_fund"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    target_amount = db.Column(DecimalText, nullable=False, default=ZERO)
    target_date = db.Column(db.Date, nullable=True)
    icon = db.Column(db.String(16), default="🎯")
    note = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=_now)
    # A spent/finished goal is archived: hidden from the active list, kept for
    # history. Set by the redeem/spend flow (or manually).
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    allocations = db.relationship(
        "FundAllocation", backref="fund", cascade="all, delete-orphan",
        order_by="FundAllocation.created_at",
    )


class FundAllocation(db.Model):
    """A fixed ₹ amount of one asset (or cash account) earmarked for a goal."""
    __tablename__ = "fund_allocation"
    id = db.Column(db.Integer, primary_key=True)
    fund_id = db.Column(db.Integer, db.ForeignKey("sinking_fund.id"), nullable=False)
    source_kind = db.Column(db.String(8), nullable=False)   # mf|gold|deposit|stock|cash
    source_ref_id = db.Column(db.Integer, nullable=False)   # holding/deposit/account id
    amount = db.Column(DecimalText, nullable=False, default=ZERO)
    created_at = db.Column(db.DateTime, default=_now)


# ---------------------------------------------------------------------------
# Mutual funds
# ---------------------------------------------------------------------------
class MutualFundHolding(db.Model):
    __tablename__ = "mf_holding"
    id = db.Column(db.Integer, primary_key=True)
    scheme_code = db.Column(db.String(20), nullable=False, index=True)
    scheme_name = db.Column(db.String(160), nullable=False)
    fund_house = db.Column(db.String(120), default="")
    plan_type = db.Column(db.String(10), default="direct")   # direct | regular
    asset_type = db.Column(db.String(10), default="equity")  # equity | debt
    goal = db.Column(db.String(80), default="")
    created_at = db.Column(db.DateTime, default=_now)
    transactions = db.relationship(
        "MFTransaction", backref="holding", cascade="all, delete-orphan",
        order_by="MFTransaction.date",
    )


class MFTransaction(db.Model):
    __tablename__ = "mf_txn"
    id = db.Column(db.Integer, primary_key=True)
    holding_id = db.Column(db.Integer, db.ForeignKey("mf_holding.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(6), nullable=False, default="sip")  # buy | sip | sell
    amount = db.Column(DecimalText, nullable=False, default=ZERO)
    units = db.Column(DecimalText, nullable=False, default=ZERO)
    nav = db.Column(DecimalText, nullable=False, default=ZERO)
    tags = db.Column(db.String(200), default="")
    # Set when this installment was generated by a SIP plan (vs entered by hand).
    sip_plan_id = db.Column(db.Integer, db.ForeignKey("sip_plan.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=_now)


class SIPPlan(db.Model):
    """A recurring monthly investment into one mutual fund holding.

    Owns backfill (past installments, asset-only) + future installments (units
    bought at that day's NAV, plus an optional cash debit from ``account``).
    ``step_up_pct`` raises the monthly amount by that percent every 12 months
    from ``start_date`` (annual step-up SIP).
    """
    __tablename__ = "sip_plan"
    id = db.Column(db.Integer, primary_key=True)
    holding_id = db.Column(db.Integer, db.ForeignKey("mf_holding.id"), nullable=False)
    amount = db.Column(DecimalText, nullable=False, default=ZERO)   # base monthly amount
    day_of_month = db.Column(db.Integer, default=1)
    start_date = db.Column(db.Date, nullable=False)
    step_up_pct = db.Column(DecimalText, nullable=False, default=ZERO)  # annual %, e.g. 10
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    tags = db.Column(db.String(200), default="")
    active = db.Column(db.Boolean, default=True, nullable=False)
    next_run_date = db.Column(db.Date, nullable=True)  # next future installment to process
    note = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=_now)

    holding = db.relationship("MutualFundHolding")
    account = db.relationship("Account")


# ---------------------------------------------------------------------------
# Gold
# ---------------------------------------------------------------------------
class GoldHolding(db.Model):
    __tablename__ = "gold_holding"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="Digital gold")
    provider = db.Column(db.String(80), default="PhonePe / SafeGold")
    created_at = db.Column(db.DateTime, default=_now)
    transactions = db.relationship(
        "GoldTransaction", backref="holding", cascade="all, delete-orphan",
        order_by="GoldTransaction.date",
    )


class GoldTransaction(db.Model):
    __tablename__ = "gold_txn"
    id = db.Column(db.Integer, primary_key=True)
    holding_id = db.Column(db.Integer, db.ForeignKey("gold_holding.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(4), nullable=False, default="buy")  # buy | sell
    grams = db.Column(DecimalText, nullable=False, default=ZERO)
    price_per_gram = db.Column(DecimalText, nullable=False, default=ZERO)
    amount = db.Column(DecimalText, nullable=False, default=ZERO)
    provider = db.Column(db.String(80), default="PhonePe / SafeGold")
    created_at = db.Column(db.DateTime, default=_now)


# ---------------------------------------------------------------------------
# Deposits (FD / RD)
# ---------------------------------------------------------------------------
class Deposit(db.Model):
    __tablename__ = "deposit"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(4), nullable=False, default="FD")  # FD | RD
    bank = db.Column(db.String(100), default="")
    principal = db.Column(DecimalText, default=ZERO)      # FD lump sum
    installment = db.Column(DecimalText, default=ZERO)    # RD monthly
    interest_rate = db.Column(DecimalText, nullable=False, default=ZERO)  # annual %, e.g. 7.10
    compounding = db.Column(db.String(12), default="quarterly")  # monthly|quarterly|half_yearly|yearly
    start_date = db.Column(db.Date, nullable=False)
    tenure_months = db.Column(db.Integer, nullable=False, default=12)
    note = db.Column(db.String(200), default="")
    # "Paid from" cash account. For an RD this drives monthly auto-contributions
    # (like a SIP); ``next_run_date`` is the next future installment to debit.
    # For an FD it's the account the one-shot principal outflow came from.
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    next_run_date = db.Column(db.Date, nullable=True)   # RD only
    # Close lifecycle: on maturity (auto) or an early manual close, the proceeds
    # are deposited back into a cash account and the deposit leaves the net-worth
    # bucket. ``closed_on`` set == closed.
    closed_on = db.Column(db.Date, nullable=True)
    closed_value = db.Column(DecimalText, nullable=False, default=ZERO)
    close_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=_now)

    account = db.relationship("Account", foreign_keys=[account_id])
    close_account = db.relationship("Account", foreign_keys=[close_account_id])

    @property
    def is_closed(self) -> bool:
        return self.closed_on is not None


# ---------------------------------------------------------------------------
# EPF
# ---------------------------------------------------------------------------
class EPFAccount(db.Model):
    __tablename__ = "epf_account"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="EPF")
    member_id = db.Column(db.String(60), default="")
    created_at = db.Column(db.DateTime, default=_now)
    entries = db.relationship(
        "EPFEntry", backref="account", cascade="all, delete-orphan",
        order_by="EPFEntry.month",
    )


class EPFEntry(db.Model):
    __tablename__ = "epf_entry"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("epf_account.id"), nullable=False)
    month = db.Column(db.Date, nullable=False)  # 1st of the month
    entry_type = db.Column(db.String(12), default="contribution")  # contribution | interest
    employee_share = db.Column(DecimalText, default=ZERO)
    employer_share = db.Column(DecimalText, default=ZERO)
    interest_amount = db.Column(DecimalText, default=ZERO)
    note = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=_now)


# ---------------------------------------------------------------------------
# Stock (minimal)
# ---------------------------------------------------------------------------
class StockHolding(db.Model):
    __tablename__ = "stock_holding"
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(100), default="")
    created_at = db.Column(db.DateTime, default=_now)
    transactions = db.relationship(
        "StockTransaction", backref="holding", cascade="all, delete-orphan",
        order_by="StockTransaction.date",
    )


class StockTransaction(db.Model):
    __tablename__ = "stock_txn"
    id = db.Column(db.Integer, primary_key=True)
    holding_id = db.Column(db.Integer, db.ForeignKey("stock_holding.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    qty = db.Column(DecimalText, nullable=False, default=ZERO)
    price_usd = db.Column(DecimalText, nullable=False, default=ZERO)
    created_at = db.Column(db.DateTime, default=_now)


# ---------------------------------------------------------------------------
# Prices, snapshots, alerts, settings
# ---------------------------------------------------------------------------
class PriceCache(db.Model):
    __tablename__ = "price_cache"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    price = db.Column(DecimalText, nullable=False, default=ZERO)
    currency = db.Column(db.String(6), default="INR")
    as_of = db.Column(db.Date, nullable=True)         # e.g. NAV date
    fetched_at = db.Column(db.DateTime, default=_now)
    ok = db.Column(db.Boolean, default=True)
    meta = db.Column(db.String(200), default="")


class NetWorthSnapshot(db.Model):
    __tablename__ = "networth_snapshot"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    cash_bank = db.Column(DecimalText, default=ZERO)
    funds = db.Column(DecimalText, default=ZERO)
    mf = db.Column(DecimalText, default=ZERO)
    gold = db.Column(DecimalText, default=ZERO)
    deposits = db.Column(DecimalText, default=ZERO)
    epf = db.Column(DecimalText, default=ZERO)
    stock = db.Column(DecimalText, default=ZERO)
    total = db.Column(DecimalText, default=ZERO)


class Alert(db.Model):
    __tablename__ = "alert"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(16), nullable=False, default="info")
    message = db.Column(db.String(300), nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    dedupe_key = db.Column(db.String(120), nullable=True, index=True)
    # optional action hook (e.g. record-it for a recurring rule)
    action = db.Column(db.String(40), default="")
    ref_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_now)


class Setting(db.Model):
    __tablename__ = "setting"
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(300), default="")

    @staticmethod
    def get(key, default=None):
        row = db.session.get(Setting, key)
        return row.value if row and row.value not in (None, "") else default

    @staticmethod
    def set(key, value):
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
        return row

"""Realistic sample data so every screen has something to show immediately.

Idempotent: clears app tables first, then rebuilds. Dates are relative to
today (IST) so the current and previous month always have data.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ..extensions import db
from ..models import (
    Account, Category, Transaction, PayeeMemory, BudgetLine, RecurringRule,
    SinkingFund, FundAllocation, MutualFundHolding, MFTransaction, GoldHolding, GoldTransaction,
    Deposit, EPFAccount, EPFEntry, StockHolding, StockTransaction, PriceCache,
    NetWorthSnapshot, Alert, Setting,
)
from ..money import money
from ..timeutil import today_ist, month_start, prev_month_start, next_month_start, add_months
from .budget import default_budget_month

D = Decimal


def _clear():
    for model in (
        Transaction, PayeeMemory, BudgetLine, RecurringRule, SinkingFund,
        MFTransaction, MutualFundHolding, GoldTransaction, GoldHolding,
        Deposit, EPFEntry, EPFAccount, StockTransaction, StockHolding,
        PriceCache, NetWorthSnapshot, Alert, Account, Category, Setting,
    ):
        db.session.query(model).delete()
    db.session.commit()


def seed_scaffold() -> dict:
    """Default settings + the standard category set. No accounts, no history.

    Shared by ``seed_all`` and the ``fresh-db`` CLI command, which wants this
    scaffolding on its own so a real ledger can be started from scratch.
    Returns the category dict keyed as ``seed_all`` expects.
    """
    # ---- Settings -------------------------------------------------------
    Setting.set("theme", "light")
    Setting.set("salary_rule_window", "7")
    Setting.set("epf_interest_rate", "8.25")

    # ---- Categories -----------------------------------------------------
    def cat(name, kind, icon, group, order):
        c = Category(name=name, kind=kind, icon=icon, group=group, sort_order=order)
        db.session.add(c)
        return c

    C = {}
    C["rent"] = cat("Rent", "expense", "🏠", "Essentials", 1)
    C["groceries"] = cat("Groceries", "expense", "🥦", "Essentials", 2)
    C["utilities"] = cat("Utilities", "expense", "💡", "Essentials", 3)
    C["transport"] = cat("Transport/Fuel", "expense", "⛽", "Essentials", 4)
    C["health"] = cat("Health", "expense", "🩺", "Essentials", 5)
    C["dining"] = cat("Dining Out", "expense", "🍽️", "Lifestyle", 1)
    C["subs"] = cat("Subscriptions", "expense", "📺", "Lifestyle", 2)
    C["personal"] = cat("Personal", "expense", "🧴", "Lifestyle", 3)
    C["family"] = cat("Family", "expense", "👨‍👩‍👧", "Lifestyle", 4)
    C["giving"] = cat("Giving/Tithe", "expense", "🤲", "Giving", 1)
    C["misc"] = cat("Miscellaneous", "expense", "🔖", "Other", 1)
    C["salary"] = cat("Salary", "income", "💰", "Income", 1)
    C["interest"] = cat("Interest", "income", "🪙", "Income", 2)
    C["other_inc"] = cat("Other", "income", "➕", "Income", 3)
    # Savings categories (names/icons match services.invest_link.SAVINGS_CATEGORIES
    # so cash-linked investment purchases reuse these rather than duplicate them).
    C["mf_sav"] = cat("Mutual Funds", "savings", "📈", "Savings", 1)
    C["gold_sav"] = cat("Gold", "savings", "🪙", "Savings", 2)
    C["dep_sav"] = cat("Deposits", "savings", "🏦", "Savings", 3)
    C["epf_sav"] = cat("EPF", "savings", "🏛️", "Savings", 4)
    C["stock_sav"] = cat("Stocks", "savings", "📊", "Savings", 5)
    db.session.flush()
    return C


def seed_all():
    _clear()
    today = today_ist()
    this_m = month_start(today)
    last_m = prev_month_start(today)

    C = seed_scaffold()

    # ---- Accounts -------------------------------------------------------
    accts = {}
    accts["hdfc"] = Account(name="HDFC Savings", type="savings_bank", opening_balance=D("125000"),
                            icon="🏦", color="#1E6B4E", sort_order=1)
    accts["cash"] = Account(name="Cash", type="cash", opening_balance=D("3500"),
                            icon="💵", color="#B98900", sort_order=2)
    accts["phonepe"] = Account(name="PhonePe Wallet", type="wallet", opening_balance=D("1200"),
                               icon="📱", color="#5B3FA0", sort_order=3)
    accts["grocery"] = Account(name="Grocery Wallet", type="grocery_wallet", opening_balance=D("2000"),
                               icon="🛒", color="#2F855A", sort_order=4)
    for a in accts.values():
        db.session.add(a)
    db.session.flush()

    # ---- Transactions ---------------------------------------------------
    def tx(days_ago_from, dt, ttype, amount, account, category=None, payee="",
           note="", tags="", transfer_to=None, budget_month=None):
        bm = budget_month or default_budget_month(dt, ttype)
        t = Transaction(
            date=dt, amount=money(amount), type=ttype,
            account_id=account.id,
            transfer_account_id=transfer_to.id if transfer_to else None,
            category_id=category.id if category else None,
            payee=payee, note=note, tags=tags, budget_month=bm,
        )
        db.session.add(t)
        return t

    # helper to make a date in a given month
    def dm(month_first, day):
        from calendar import monthrange
        last = monthrange(month_first.year, month_first.month)[1]
        return month_first.replace(day=min(day, last))

    # Salary — last month (received near month-end -> lands in this month via salary rule)
    tx(None, dm(last_m, 28), "income", D("95000"), accts["hdfc"], C["salary"], payee="Acme Corp Payroll",
       note="Monthly salary")
    # Salary earlier -> this month proper
    tx(None, dm(this_m, 1), "income", D("95000"), accts["hdfc"], C["salary"], payee="Acme Corp Payroll",
       note="Monthly salary", budget_month=this_m)
    tx(None, dm(this_m, 5), "income", D("640"), accts["hdfc"], C["interest"], payee="HDFC Bank",
       note="Savings interest")

    # Expenses — this month
    tx(None, dm(this_m, 1), "expense", D("25000"), accts["hdfc"], C["rent"], payee="Landlord",
       note="Flat rent", tags="recurring")
    tx(None, dm(this_m, 3), "expense", D("2450"), accts["grocery"], C["groceries"], payee="More Supermarket")
    tx(None, dm(this_m, 8), "expense", D("1890"), accts["grocery"], C["groceries"], payee="Reliance Fresh")
    tx(None, dm(this_m, 11), "expense", D("560"), accts["phonepe"], C["transport"], payee="Indian Oil")
    tx(None, dm(this_m, 6), "expense", D("649"), accts["hdfc"], C["subs"], payee="Netflix", tags="recurring")
    tx(None, dm(this_m, 6), "expense", D("1299"), accts["hdfc"], C["subs"], payee="Amazon Prime")
    tx(None, dm(this_m, 9), "expense", D("2100"), accts["hdfc"], C["dining"], payee="Truffles")
    tx(None, dm(this_m, 4), "expense", D("1450"), accts["hdfc"], C["utilities"], payee="BESCOM",
       note="Electricity")
    tx(None, dm(this_m, 10), "expense", D("5000"), accts["hdfc"], C["giving"], payee="Local church",
       note="Monthly tithe")
    # A split grocery+personal run
    parent = tx(None, dm(this_m, 12), "expense", D("3200"), accts["hdfc"], None, payee="DMart",
                note="Monthly stock-up")
    db.session.flush()
    parent.splits = [
        Transaction(date=parent.date, amount=money(D("2300")), type="expense",
                    account_id=parent.account_id, category_id=C["groceries"].id,
                    budget_month=parent.budget_month, payee="DMart"),
        Transaction(date=parent.date, amount=money(D("900")), type="expense",
                    account_id=parent.account_id, category_id=C["personal"].id,
                    budget_month=parent.budget_month, payee="DMart"),
    ]

    # Transfers this month: top up wallets
    tx(None, dm(this_m, 2), "transfer", D("6000"), accts["hdfc"], transfer_to=accts["grocery"],
       note="Grocery budget top-up")
    tx(None, dm(this_m, 2), "transfer", D("2000"), accts["hdfc"], transfer_to=accts["phonepe"],
       note="PhonePe top-up")

    # Last month: fund the wallets so balances stay realistic
    tx(None, dm(last_m, 2), "transfer", D("9000"), accts["hdfc"], transfer_to=accts["grocery"],
       note="Grocery budget top-up")
    tx(None, dm(last_m, 18), "transfer", D("1500"), accts["hdfc"], transfer_to=accts["phonepe"],
       note="PhonePe top-up")

    # Expenses — last month (for month-over-month reports)
    tx(None, dm(last_m, 1), "expense", D("25000"), accts["hdfc"], C["rent"], payee="Landlord")
    tx(None, dm(last_m, 5), "expense", D("4300"), accts["grocery"], C["groceries"], payee="More Supermarket")
    tx(None, dm(last_m, 9), "expense", D("3800"), accts["grocery"], C["groceries"], payee="Reliance Fresh")
    tx(None, dm(last_m, 12), "expense", D("2600"), accts["hdfc"], C["dining"], payee="Barbeque Nation")
    tx(None, dm(last_m, 6), "expense", D("649"), accts["hdfc"], C["subs"], payee="Netflix")
    tx(None, dm(last_m, 15), "expense", D("1750"), accts["hdfc"], C["utilities"], payee="BESCOM")
    tx(None, dm(last_m, 20), "expense", D("980"), accts["phonepe"], C["transport"], payee="Uber")
    tx(None, dm(last_m, 10), "expense", D("5000"), accts["hdfc"], C["giving"], payee="Local church")
    tx(None, dm(last_m, 25), "expense", D("1500"), accts["hdfc"], C["health"], payee="Apollo Pharmacy")

    # ---- Payee memory ---------------------------------------------------
    for payee, c, a, t in [
        ("Netflix", C["subs"], accts["hdfc"], "expense"),
        ("More Supermarket", C["groceries"], accts["grocery"], "expense"),
        ("Landlord", C["rent"], accts["hdfc"], "expense"),
        ("Acme Corp Payroll", C["salary"], accts["hdfc"], "income"),
        ("Indian Oil", C["transport"], accts["phonepe"], "expense"),
    ]:
        db.session.add(PayeeMemory(payee=payee, last_category_id=c.id,
                                   last_account_id=a.id, last_type=t, uses=3))

    # ---- Budget lines ---------------------------------------------------
    plan = {
        "rent": 25000, "groceries": 9000, "utilities": 2500, "transport": 3000,
        "health": 2000, "dining": 4000, "subs": 2000, "personal": 1500,
        "family": 3000, "giving": 5000, "misc": 2000,
    }
    income_plan = {"salary": 95000, "interest": 600}
    savings_plan = {"mf_sav": 17500, "dep_sav": 5000}
    for m in (last_m, this_m):
        for key, amt in plan.items():
            db.session.add(BudgetLine(budget_month=m, category_id=C[key].id, planned_amount=money(amt)))
        for key, amt in income_plan.items():
            db.session.add(BudgetLine(budget_month=m, category_id=C[key].id, planned_amount=money(amt)))
        for key, amt in savings_plan.items():
            db.session.add(BudgetLine(budget_month=m, category_id=C[key].id, planned_amount=money(amt)))

    # ---- Recurring rules ------------------------------------------------
    db.session.add(RecurringRule(payee="Landlord", amount=money(25000), type="expense",
                                 category_id=C["rent"].id, account_id=accts["hdfc"].id,
                                 frequency="monthly", day_of_month=1, mode="auto_create",
                                 next_due_date=next_month_start(today), tags="recurring",
                                 note="Flat rent"))
    db.session.add(RecurringRule(payee="Netflix", amount=money(649), type="expense",
                                 category_id=C["subs"].id, account_id=accts["hdfc"].id,
                                 frequency="monthly", day_of_month=6, mode="auto_create",
                                 next_due_date=dm(next_month_start(today), 6), tags="recurring"))
    db.session.add(RecurringRule(payee="BESCOM electricity", amount=money(1500), type="expense",
                                 category_id=C["utilities"].id, account_id=accts["hdfc"].id,
                                 frequency="monthly", day_of_month=15, mode="remind_only",
                                 next_due_date=dm(today, 15) if today.day <= 15 else dm(next_month_start(today), 15),
                                 note="Varies month to month"))

    # ---- Mutual fund + SIP history -------------------------------------
    mf = MutualFundHolding(scheme_code="122639",
                           scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                           fund_house="PPFAS Mutual Fund", plan_type="direct",
                           asset_type="equity", goal="Wealth")
    db.session.add(mf)
    db.session.flush()
    # An older lump-sum buy (>12 months) so a later sell realizes LTCG.
    db.session.add(MFTransaction(holding_id=mf.id, date=dm(add_months(this_m, -14), 10),
                                 type="buy", amount=money(40000), units=D("623.05"), nav=D("64.20")))
    nav_hist = [(6, D("72.50")), (5, D("74.10")), (4, D("73.20")), (3, D("77.80")),
                (2, D("79.40")), (1, D("81.10"))]
    for months_ago, nav in nav_hist:
        d = dm(add_months(this_m, -months_ago), 5)
        amt = money(5000)
        units = (amt / nav)
        db.session.add(MFTransaction(holding_id=mf.id, date=d, type="sip", amount=amt,
                                     units=units, nav=nav))
    # A partial sell last month -> long-term (matches the 14-month-old lot, FIFO)
    db.session.add(MFTransaction(holding_id=mf.id, date=dm(add_months(this_m, -1), 15),
                                 type="sell", amount=money("32200"), units=D("400"), nav=D("80.50")))

    # An ELSS fund with 80C-tagged SIPs (counts toward Section 80C)
    elss = MutualFundHolding(scheme_code="135800",
                             scheme_name="Mirae Asset ELSS Tax Saver Fund - Direct Plan - Growth",
                             fund_house="Mirae Asset Mutual Fund", plan_type="direct",
                             asset_type="equity", goal="Tax saving")
    db.session.add(elss)
    db.session.flush()
    for months_ago, nav in [(3, D("48.20")), (2, D("49.10")), (1, D("50.40"))]:
        d = dm(add_months(this_m, -months_ago), 7)
        amt = money(12500)
        db.session.add(MFTransaction(holding_id=elss.id, date=d, type="sip", amount=amt,
                                     units=(amt / nav), nav=nav, tags="80C"))
    # This month's ELSS SIP, funded from HDFC -> a linked "savings" cash-out.
    # Cash drops ₹12,500 while the MF bucket rises, so net worth is unchanged —
    # demonstrating the investment/cash link and the budget Savings section.
    from .invest_link import sync_cash
    sip_now = MFTransaction(holding_id=elss.id, date=dm(this_m, 7), type="sip",
                            amount=money(12500), units=(money(12500) / D("50.40")),
                            nav=D("50.40"))
    db.session.add(sip_now)
    db.session.flush()
    sync_cash("mf", sip_now.id, account_id=accts["hdfc"].id, amount=money(12500),
              on=sip_now.date, flow="out", note=elss.scheme_name)

    # ---- Gold -----------------------------------------------------------
    gold = GoldHolding(name="Digital gold", provider="PhonePe / SafeGold")
    db.session.add(gold)
    db.session.flush()
    db.session.add(GoldTransaction(holding_id=gold.id, date=dm(add_months(this_m, -4), 15),
                                   type="buy", grams=D("5.0000"), price_per_gram=money(7200),
                                   amount=money(36000), provider="PhonePe / SafeGold"))
    db.session.add(GoldTransaction(holding_id=gold.id, date=dm(add_months(this_m, -1), 20),
                                   type="buy", grams=D("3.0000"), price_per_gram=money(8100),
                                   amount=money(24300), provider="PhonePe / SafeGold"))
    # A small sell this month -> short-term gold gain (slab)
    db.session.add(GoldTransaction(holding_id=gold.id, date=dm(this_m, 8),
                                   type="sell", grams=D("1.0000"), price_per_gram=money(8850),
                                   amount=money(8850), provider="PhonePe / SafeGold"))

    # ---- Deposit (FD) ---------------------------------------------------
    fd = Deposit(kind="FD", bank="HDFC Bank", principal=money(200000),
                 interest_rate=money("7.10"), compounding="quarterly",
                 start_date=add_months(this_m, -11), tenure_months=24,
                 note="Emergency reserve")
    db.session.add(fd)
    rd = Deposit(kind="RD", bank="SBI", installment=money(5000),
                 interest_rate=money("6.80"), compounding="quarterly",
                 start_date=add_months(this_m, -6), tenure_months=12,
                 note="Short-term goal")
    db.session.add(rd)
    db.session.flush()
    # Auto-contribute the RD from HDFC going forward (past months stay asset-only).
    from .rd import sync_rd_plan
    sync_rd_plan(rd, accts["hdfc"].id)

    # ---- EPF ------------------------------------------------------------
    epf = EPFAccount(name="EPF", member_id="KN/BNG/0012345/000/0004567")
    db.session.add(epf)
    db.session.flush()
    running_start = add_months(this_m, -8)
    for i in range(8):
        m = add_months(running_start, i)
        db.session.add(EPFEntry(account_id=epf.id, month=m, entry_type="contribution",
                                employee_share=money(1800), employer_share=money(1800)))

    # ---- Stock ----------------------------------------------------------
    stock = StockHolding(ticker="AAPL", name="Apple Inc.")
    db.session.add(stock)
    db.session.flush()
    db.session.add(StockTransaction(holding_id=stock.id, date=add_months(this_m, -7),
                                    qty=D("5"), price_usd=money("182.50")))

    # ---- Price cache (so valuations work fully offline) -----------------
    def price(key, val, currency="INR", meta="", as_of=None):
        db.session.add(PriceCache(key=key, price=money(val) if currency != "units" else val,
                                  currency=currency, as_of=as_of or today, meta=meta))
    price("mf:122639", D("82.30"), meta="Parag Parikh Flexi Cap")
    price("mf:135800", D("51.60"), meta="Mirae ELSS Tax Saver")
    price("gold:inr_per_gram", D("8850"), meta="derived GC=F x USDINR")
    price("fx:usdinr", D("86.40"), currency="USD", meta="USDINR=X")
    price("stock:AAPL", D("232.10"), currency="USD", meta="Apple Inc.")

    # ---- Sinking-fund goals (earmark slices of the assets above) --------
    db.session.flush()   # ensure fd / mf ids exist
    emergency = SinkingFund(name="Emergency fund", target_amount=money(500000),
                            target_date=add_months(this_m, 12), icon="🛟",
                            note="Six months of expenses, kept liquid")
    laptop = SinkingFund(name="New laptop", target_amount=money(120000),
                         target_date=add_months(this_m, 5), icon="💻")
    house = SinkingFund(name="House down payment", target_amount=money(2000000),
                        target_date=add_months(this_m, 48), icon="🏠")
    for fnd in (emergency, laptop, house):
        db.session.add(fnd)
    db.session.flush()
    for fnd, kind, ref, amt in [
        (emergency, "deposit", fd.id, 160000),        # part of the HDFC FD
        (emergency, "cash", accts["hdfc"].id, 40000),  # a slice of bank cash
        (laptop, "cash", accts["hdfc"].id, 20000),
        (house, "mf", mf.id, 25000),                   # part of the Parag Parikh MF
    ]:
        db.session.add(FundAllocation(fund_id=fnd.id, source_kind=kind,
                                      source_ref_id=ref, amount=money(amt)))

    db.session.commit()

    # ---- Net-worth snapshots (trend) -----------------------------------
    _seed_snapshots(today)
    db.session.commit()


def _seed_snapshots(today):
    """~45 days of upward-trending snapshots so charts have history."""
    base = {
        "cash_bank": D("118000"), "mf": D("242000"),
        "gold": D("64000"), "deposits": D("205000"), "epf": D("96000"),
        "stock": D("78000"),
    }
    for i in range(45, -1, -1):
        d = today - timedelta(days=i)
        grow = (Decimal(45 - i) / Decimal(45))
        buckets = {}
        for k, v in base.items():
            # gentle drift + a little bucket-specific slope
            buckets[k] = money(v * (Decimal("1") + grow * Decimal("0.06")))
        total = money(sum(buckets.values()))
        db.session.add(NetWorthSnapshot(date=d, total=total, **buckets))

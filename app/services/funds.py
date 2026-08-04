"""Sinking-fund goals backed by earmarked slices of existing assets.

A goal holds no money of its own. Each :class:`FundAllocation` earmarks a fixed
₹ amount of one source — an MF holding, gold, an FD/RD, a stock, or a cash
account. "Saved so far" is the sum of a goal's allocations, each clamped to the
current value of its source (so a volatile holding that drops below its earmark
shows a shortfall rather than over-counting).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from ..extensions import db
from ..models import SinkingFund, FundAllocation
from ..money import ZERO, money, quantize4
from ..timeutil import today_ist, months_between

SOURCE_ICONS = {"mf": "📈", "gold": "🪙", "deposit": "🏦", "stock": "📊", "cash": "🏦"}


# ---------------------------------------------------------------------------
# Source valuation & labels
# ---------------------------------------------------------------------------
def source_current_value(kind: str, ref_id: int) -> Decimal:
    """Live value (INR) of one allocatable source. 0 if it can't be found."""
    if kind == "cash":
        from .accounts import account_balance
        return money(max(account_balance(ref_id), ZERO))
    if kind == "mf":
        from ..models import MutualFundHolding
        from . import mf as mf_svc
        h = db.session.get(MutualFundHolding, ref_id)
        if not h:
            return ZERO
        m = mf_svc.holding_metrics(h)
        return money(m["current_value"] if m["current_value"] is not None else m["invested"])
    if kind == "gold":
        from . import gold as gold_svc
        return money(gold_svc.current_value())
    if kind == "deposit":
        from ..models import Deposit
        from .calculators import deposit_summary
        d = db.session.get(Deposit, ref_id)
        if not d or d.closed_on:      # closed -> value has moved to cash
            return ZERO
        return deposit_summary(d)["accrued_value"]
    if kind == "stock":
        from ..models import StockHolding
        from . import market as market_svc
        h = db.session.get(StockHolding, ref_id)
        if not h:
            return ZERO
        v = market_svc.stock_metrics(h)["value_inr"]
        return money(v) if v is not None else market_svc.stock_metrics(h)["invested_inr"]
    return ZERO


def source_label(kind: str, ref_id: int) -> str:
    if kind == "cash":
        from ..models import Account
        a = db.session.get(Account, ref_id)
        return a.name if a else "Cash"
    if kind == "mf":
        from ..models import MutualFundHolding
        h = db.session.get(MutualFundHolding, ref_id)
        return h.scheme_name if h else "Mutual fund"
    if kind == "gold":
        return "Digital gold"
    if kind == "deposit":
        from ..models import Deposit
        d = db.session.get(Deposit, ref_id)
        return f"{d.bank} {d.kind}".strip() if d else "Deposit"
    if kind == "stock":
        from ..models import StockHolding
        h = db.session.get(StockHolding, ref_id)
        return h.ticker if h else "Stock"
    return kind


def source_icon(kind: str, ref_id: int) -> str:
    if kind == "cash":
        from ..models import Account
        a = db.session.get(Account, ref_id)
        return a.icon if a and a.icon else "🏦"
    return SOURCE_ICONS.get(kind, "🎯")


# ---------------------------------------------------------------------------
# Allocation index & coverage
# ---------------------------------------------------------------------------
def _alloc_index() -> dict:
    """(kind, ref_id) -> {'earmarked': total ₹ across all funds, 'items': [alloc]}."""
    idx: dict = {}
    for a in FundAllocation.query.all():
        key = (a.source_kind, a.source_ref_id)
        e = idx.setdefault(key, {"earmarked": ZERO, "items": []})
        e["earmarked"] += money(a.amount)
        e["items"].append(a)
    return idx


def _coverage(kind, ref_id, earmarked: Decimal, value_cache: dict) -> Decimal:
    """Fraction of the earmarked total the source can actually cover (<=1)."""
    if earmarked <= 0:
        return Decimal(1)
    if (kind, ref_id) not in value_cache:
        value_cache[(kind, ref_id)] = source_current_value(kind, ref_id)
    value = value_cache[(kind, ref_id)]
    cov = value / earmarked
    return cov if cov < 1 else Decimal(1)


def earmarked_on_source(kind: str, ref_id: int) -> Decimal:
    """Total ₹ earmarked against one source across all goals."""
    total = ZERO
    for a in FundAllocation.query.filter_by(source_kind=kind, source_ref_id=ref_id).all():
        total += money(a.amount)
    return money(total)


def available_to_allocate(kind: str, ref_id: int) -> Decimal:
    """How much of a source is still free to earmark (value minus earmarked)."""
    return money(max(source_current_value(kind, ref_id) - earmarked_on_source(kind, ref_id), ZERO))


# ---------------------------------------------------------------------------
# Fund status (progress from allocations)
# ---------------------------------------------------------------------------
def fund_saved(fund, alloc_index: dict | None = None, value_cache: dict | None = None) -> Decimal:
    alloc_index = alloc_index if alloc_index is not None else _alloc_index()
    value_cache = value_cache if value_cache is not None else {}
    total = ZERO
    for a in fund.allocations:
        key = (a.source_kind, a.source_ref_id)
        earmarked = alloc_index.get(key, {}).get("earmarked", money(a.amount))
        total += money(a.amount) * _coverage(a.source_kind, a.source_ref_id, earmarked, value_cache)
    return money(total)


def fund_status(fund, alloc_index: dict | None = None, value_cache: dict | None = None) -> dict:
    """Progress, required monthly top-up, on-track status, and the allocation list."""
    alloc_index = alloc_index if alloc_index is not None else _alloc_index()
    value_cache = value_cache if value_cache is not None else {}

    saved = fund_saved(fund, alloc_index, value_cache)
    target = money(fund.target_amount)
    remaining = target - saved
    today = today_ist()
    months_left = months_between(today, fund.target_date) if fund.target_date else None
    overdue = bool(fund.target_date and today > fund.target_date)

    # months_between floors at 0, so "no months left" covers both a date later
    # this month and one already gone: either way the whole remainder is due
    # now, and `overdue` is what tells the two apart.
    if remaining <= 0:
        required = ZERO
    elif months_left and months_left > 0:
        # Rounded up to the whole rupee. The card states this as the monthly
        # figure to set aside, and rounding down would land short of the target
        # by the time the date arrives.
        required = money((remaining / Decimal(months_left))
                         .quantize(Decimal("1"), rounding=ROUND_CEILING))
    else:
        required = max(remaining, ZERO)

    pct = 0
    if target > 0:
        pct = int((saved / target * 100).to_integral_value())
        pct = max(0, min(pct, 100))

    if saved >= target and target > 0:
        status = "complete"
    elif fund.target_date and today > fund.target_date:
        status = "behind"
    elif fund.target_date:
        start = (fund.created_at.date() if fund.created_at else today)
        total = max(months_between(start, fund.target_date), 1)
        elapsed = months_between(start, today)
        expected = money(target * Decimal(min(elapsed, total)) / Decimal(total))
        status = "on_track" if saved + Decimal("0.01") >= expected * Decimal("0.9") else "behind"
    else:
        status = "on_track"

    allocs = []
    for a in fund.allocations:
        key = (a.source_kind, a.source_ref_id)
        earmarked = alloc_index.get(key, {}).get("earmarked", money(a.amount))
        cov = _coverage(a.source_kind, a.source_ref_id, earmarked, value_cache)
        amount = money(a.amount)
        allocs.append({
            "id": a.id, "kind": a.source_kind, "ref_id": a.source_ref_id,
            "label": source_label(a.source_kind, a.source_ref_id),
            "icon": source_icon(a.source_kind, a.source_ref_id),
            "amount": amount, "effective": money(amount * cov), "short": cov < 1,
        })

    return {
        "fund": fund, "saved": saved, "target": target,
        "remaining": max(remaining, ZERO), "months_left": months_left,
        "required_monthly": required, "overdue": overdue,
        "pct": pct, "status": status, "allocs": allocs,
    }


def all_fund_statuses() -> list[dict]:
    """Active (non-archived) goals only."""
    idx = _alloc_index()
    vc: dict = {}
    funds = (SinkingFund.query.filter(SinkingFund.is_archived.is_(False))
             .order_by(SinkingFund.created_at).all())
    return [fund_status(f, idx, vc) for f in funds]


def archived_fund_statuses() -> list[dict]:
    """Spent/finished goals, kept for history."""
    idx = _alloc_index()
    vc: dict = {}
    funds = (SinkingFund.query.filter(SinkingFund.is_archived.is_(True))
             .order_by(SinkingFund.created_at).all())
    return [fund_status(f, idx, vc) for f in funds]


# ---------------------------------------------------------------------------
# Sources list (for the allocate picker) & reverse earmark lookup
# ---------------------------------------------------------------------------
def list_sources() -> list[dict]:
    """Every allocatable source with its value / earmarked / free amount.

    Only sources with a positive current value are returned."""
    from ..models import (MutualFundHolding, Deposit, StockHolding, GoldHolding, Account)
    idx = _alloc_index()
    out = []

    def add(kind, ref_id):
        value = source_current_value(kind, ref_id)
        if value <= 0:
            return
        earmarked = idx.get((kind, ref_id), {}).get("earmarked", ZERO)
        out.append({
            "kind": kind, "ref_id": ref_id,
            "label": source_label(kind, ref_id), "icon": source_icon(kind, ref_id),
            "value": money(value), "earmarked": money(earmarked),
            "available": money(max(value - earmarked, ZERO)),
        })

    for h in MutualFundHolding.query.order_by(MutualFundHolding.scheme_name).all():
        add("mf", h.id)
    for g in GoldHolding.query.all():
        add("gold", g.id)
    for d in Deposit.query.filter(Deposit.closed_on.is_(None)).order_by(Deposit.start_date).all():
        add("deposit", d.id)
    for s in StockHolding.query.order_by(StockHolding.ticker).all():
        add("stock", s.id)
    from ..models import CASH_LIKE_TYPES
    for a in Account.query.filter(Account.is_archived.is_(False),
                                  Account.type.in_(CASH_LIKE_TYPES)).all():
        add("cash", a.id)
    return out


def earmark_lookup() -> dict:
    """{kind: {ref_id: [{'name','icon','amount'}]}} — for the reverse view on
    each holding card ("₹X earmarked for <goal>")."""
    out: dict = {}
    for a in FundAllocation.query.all():
        fund = a.fund
        out.setdefault(a.source_kind, {}).setdefault(a.source_ref_id, []).append(
            {"name": fund.name, "icon": fund.icon, "amount": money(a.amount)})
    return out


# ---------------------------------------------------------------------------
# Redeem (liquidate a source to cash) & spend a goal
# ---------------------------------------------------------------------------
def redeem_source(kind: str, ref_id: int, *, amount, account_id, on) -> "Decimal":
    """Liquidate ~₹``amount`` of one source into ``account_id`` (cash).

    Sells exactly the earmarked ₹ worth of an MF/gold/stock holding at the
    current price; closes a deposit **in full** (FDs can't be partially closed —
    the surplus over the earmark just lands in cash). Cash needs no sale.
    Returns the proceeds actually credited (0 if it couldn't be priced).
    """
    amount = money(amount)
    if amount <= 0:
        return ZERO
    if kind == "cash":
        return amount                      # already liquid, nothing to sell

    # For a market holding we sell whole-ish units at the current price, so the
    # cash we actually receive is ``units_sold × price`` (≈ the earmark, within
    # unit rounding). Crediting exactly that keeps the redemption net-worth-neutral
    # (the bucket loses precisely what cash gains).
    if kind == "mf":
        from ..models import MutualFundHolding, MFTransaction
        from . import mf as mf_svc, invest_link
        h = db.session.get(MutualFundHolding, ref_id)
        if not h:
            return ZERO
        nav = mf_svc.current_nav(h.scheme_code)
        if not nav or nav <= 0:
            return ZERO
        units = quantize4(amount / nav)
        proceeds = money(units * nav)
        t = MFTransaction(holding_id=h.id, date=on, type="sell", amount=proceeds,
                          units=units, nav=money(nav), tags="redeem")
        db.session.add(t)
        db.session.flush()
        invest_link.sync_cash("mf", t.id, account_id=account_id, amount=proceeds,
                              on=on, flow="in", note=f"Redeemed · {h.scheme_name}")
        return proceeds

    if kind == "gold":
        from ..models import GoldHolding, GoldTransaction
        from . import gold as gold_svc, invest_link
        h = db.session.get(GoldHolding, ref_id) or GoldHolding.query.first()
        rate = gold_svc.current_rate()
        if not h or not rate or rate <= 0:
            return ZERO
        grams = quantize4(amount / rate)
        proceeds = money(grams * rate)
        t = GoldTransaction(holding_id=h.id, date=on, type="sell",
                            grams=grams, price_per_gram=money(rate),
                            amount=proceeds, provider=h.provider)
        db.session.add(t)
        db.session.flush()
        invest_link.sync_cash("gold", t.id, account_id=account_id, amount=proceeds,
                              on=on, flow="in", note="Redeemed gold")
        return proceeds

    if kind == "stock":
        from ..models import StockHolding, StockTransaction
        from . import market as market_svc, invest_link
        h = db.session.get(StockHolding, ref_id)
        if not h:
            return ZERO
        m = market_svc.stock_metrics(h)
        inr_per_share = money((m["price_usd"] or ZERO) * m["fx"])
        if inr_per_share <= 0:
            return ZERO
        qty = quantize4(amount / inr_per_share)
        proceeds = money(qty * inr_per_share)
        t = StockTransaction(holding_id=h.id, date=on, qty=-qty,
                             price_usd=money(m["price_usd"]))
        db.session.add(t)
        db.session.flush()
        invest_link.sync_cash("stock", t.id, account_id=account_id, amount=proceeds,
                              on=on, flow="in", note=f"Redeemed · {h.ticker}")
        return proceeds

    if kind == "deposit":
        from ..models import Deposit
        from .calculators import deposit_summary
        from . import deposit_actions
        d = db.session.get(Deposit, ref_id)
        if not d or d.closed_on:
            return ZERO
        proceeds = deposit_summary(d, on)["accrued_value"]
        deposit_actions.close_deposit(d, on=on, proceeds=proceeds, account_id=account_id)
        return money(proceeds)

    return ZERO


def spend_goal(fund, *, alloc_ids, proceeds_account_id, expense=None,
               archive=True) -> dict:
    """Liquidate selected earmarks to cash, record the purchase, archive the goal.

    ``alloc_ids`` — ids of this fund's allocations to redeem into
    ``proceeds_account_id``. ``expense`` — optional dict
    (amount/category_id/account_id/payee/date/note) recorded as a real expense.
    ``archive`` — mark the goal done and release any remaining earmarks. Commits.
    """
    on = (expense or {}).get("date") or today_ist()
    ids = {int(x) for x in (alloc_ids or [])}
    redeemed = ZERO
    for a in list(fund.allocations):
        if a.id not in ids:
            continue
        redeemed += redeem_source(a.source_kind, a.source_ref_id,
                                  amount=money(a.amount),
                                  account_id=proceeds_account_id, on=on)
        db.session.delete(a)

    exp_amount = money(expense.get("amount")) if expense and expense.get("amount") else ZERO
    exp_txn = None
    if exp_amount > 0 and expense.get("account_id"):
        from ..models import Transaction
        from .budget import default_budget_month
        exp_txn = Transaction(
            date=on, amount=exp_amount, type="expense",
            account_id=int(expense["account_id"]),
            category_id=(int(expense["category_id"]) if expense.get("category_id") else None),
            payee=(expense.get("payee") or "").strip(),
            note=(expense.get("note") or "").strip(),
            budget_month=default_budget_month(on, "expense"))
        db.session.add(exp_txn)

    if archive:
        fund.is_archived = True
        for a in list(fund.allocations):   # release any earmarks left over
            db.session.delete(a)

    db.session.commit()
    return {"redeemed": money(redeemed), "expense": exp_amount,
            "archived": bool(archive)}

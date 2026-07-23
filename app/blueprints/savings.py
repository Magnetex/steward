"""Savings page with tabs. Phase 6 = Mutual Funds; Phase 7 adds the rest."""
from __future__ import annotations

import json
from decimal import Decimal

from flask import Blueprint, render_template, request, jsonify, make_response, redirect, url_for, flash, abort

from ..extensions import db
from ..models import MutualFundHolding, MFTransaction, MF_TXN_TYPES, SIPPlan
from ..money import money, to_decimal, ZERO, quantize4, fmt_inr
from ..timeutil import parse_date, today_ist
from ..services import mf as mf_svc
from ..services import sip as sip_svc
from ..services import invest_link
from ..services import accounts as acc_svc

bp = Blueprint("savings", __name__, url_prefix="/savings")

TABS = ["mf", "gold", "deposits", "epf", "stock"]
TAB_LABELS = {"mf": "Mutual funds", "gold": "Gold", "deposits": "Deposits",
              "epf": "EPF", "stock": "Stock"}


def _mf_context():
    holdings = MutualFundHolding.query.order_by(MutualFundHolding.scheme_name).all()
    rows = [{"h": h, "m": mf_svc.holding_metrics(h)} for h in holdings]
    total_value = sum((r["m"]["current_value"] or ZERO for r in rows), ZERO)
    total_invested = sum((r["m"]["invested"] for r in rows), ZERO)
    total_pl = total_value - total_invested
    return {
        "rows": rows,
        "holdings": holdings,
        "sips": sip_svc.all_summaries(),
        "total_value": money(total_value), "total_invested": money(total_invested),
        "total_pl": money(total_pl),
        "total_pl_pct": (total_pl / total_invested * 100).quantize(Decimal("0.01")) if total_invested > 0 else None,
        "today": today_ist().isoformat(),
    }


def _tab_context(tab):
    ctx = {"tab": tab, "tabs": TABS, "tab_labels": TAB_LABELS}
    if tab == "mf":
        ctx.update(_mf_context())
    else:
        from ..services import investments_tabs as it
        ctx.update(it.context_for(tab))
    # Cash accounts for the optional "Paid from" selector on buy/sell forms.
    ctx["cash_accounts"] = acc_svc.active_accounts()
    # Reverse "earmarked for <goal>" lookup: {kind: {ref_id: [{name,icon,amount}]}}
    from ..services import funds as funds_svc
    ctx["earmarks"] = funds_svc.earmark_lookup()
    return ctx


@bp.route("/")
def index():
    tab = request.args.get("tab", "mf")
    if tab not in TABS:
        tab = "mf"
    return render_template("savings/index.html", **_tab_context(tab))


@bp.route("/tab/<tab>")
def tabbody(tab):
    if tab not in TABS:
        abort(404)
    return render_template("savings/_" + tab + ".html", **_tab_context(tab))


# ---- Mutual fund endpoints -------------------------------------------------
@bp.route("/mf/search")
def mf_search():
    return jsonify(mf_svc.search_schemes(request.args.get("q", "")))


@bp.route("/mf/nav")
def mf_nav():
    code = request.args.get("code", "")
    on = parse_date(request.args.get("date"), today_ist())
    res = mf_svc.nav_as_of(code, on)
    if res is None:
        return jsonify({"ok": False})
    nav, d = res
    return jsonify({"ok": True, "nav": str(nav), "as_of": d.isoformat()})


@bp.route("/mf/holding/save", methods=["POST"])
def mf_holding_save():
    hid = request.form.get("id")
    h = db.session.get(MutualFundHolding, int(hid)) if hid and hid.isdigit() else MutualFundHolding()
    f = request.form
    if not (f.get("scheme_code") or "").strip():
        flash("Search and pick a scheme first.", "error")
        return redirect(url_for("savings.index", tab="mf"))
    h.scheme_code = f.get("scheme_code").strip()
    h.scheme_name = (f.get("scheme_name") or "").strip()
    h.fund_house = (f.get("fund_house") or "").strip()
    h.plan_type = f.get("plan_type") if f.get("plan_type") in ("direct", "regular") else "direct"
    h.asset_type = f.get("asset_type") if f.get("asset_type") in ("equity", "debt") else "equity"
    h.goal = (f.get("goal") or "").strip()
    if not (hid and hid.isdigit()):
        db.session.add(h)
    db.session.commit()
    mf_svc.refresh_nav(h.scheme_code)  # best effort
    flash("Holding saved.", "success")
    return redirect(url_for("savings.index", tab="mf"))


@bp.route("/mf/holding/<int:holding_id>/delete", methods=["POST"])
def mf_holding_delete(holding_id):
    h = db.session.get(MutualFundHolding, holding_id) or abort(404)
    for t in h.transactions:            # drop linked cash movements before cascade
        invest_link.unlink_cash("mf", t.id)
    db.session.delete(h)
    db.session.commit()
    flash("Holding removed.", "success")
    return redirect(url_for("savings.index", tab="mf"))


@bp.route("/mf/txn/save", methods=["POST"])
def mf_txn_save():
    f = request.form
    holding_id = f.get("holding_id", type=int)
    h = db.session.get(MutualFundHolding, holding_id) if holding_id else None
    if h is None:
        abort(404)
    ttype = f.get("type") if f.get("type") in MF_TXN_TYPES else "sip"
    amount = money(f.get("amount"))
    nav = to_decimal(f.get("nav"), ZERO)
    units = to_decimal(f.get("units"), ZERO)
    if units <= 0 and nav > 0:
        units = quantize4(amount / nav)
    t = MFTransaction(holding_id=h.id, date=parse_date(f.get("date"), today_ist()),
                      type=ttype, amount=amount, units=units, nav=nav,
                      tags=(f.get("tags") or "").strip())
    db.session.add(t)
    db.session.flush()
    invest_link.sync_cash(
        "mf", t.id, account_id=f.get("account_id", type=int),
        amount=amount, on=t.date, flow="in" if ttype == "sell" else "out",
        note=h.scheme_name)
    db.session.commit()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": "Transaction added."}})


@bp.route("/mf/txn/<int:txn_id>/delete", methods=["POST"])
def mf_txn_delete(txn_id):
    t = db.session.get(MFTransaction, txn_id) or abort(404)
    invest_link.unlink_cash("mf", t.id)
    db.session.delete(t)
    db.session.commit()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": "Transaction deleted."}})


@bp.route("/mf/refresh", methods=["POST"])
def mf_refresh():
    results = mf_svc.refresh_all_navs()
    ok = sum(1 for v in results.values() if v)
    fail = len(results) - ok
    kind = "success" if fail == 0 else "warn"
    msg = f"NAVs updated ({ok} ok" + (f", {fail} failed)" if fail else ")")
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": kind, "message": msg}})


# ---- SIP plans -------------------------------------------------------------
@bp.route("/mf/sip/save", methods=["POST"])
def mf_sip_save():
    f = request.form
    holding_id = f.get("holding_id", type=int)
    h = db.session.get(MutualFundHolding, holding_id) if holding_id else None
    if h is None:
        return _trigger({"steward-toast": {"kind": "error", "message": "Pick a fund for the SIP."}}, 200)
    amount = money(f.get("amount"))
    if amount <= 0:
        return _trigger({"steward-toast": {"kind": "error", "message": "Enter the monthly SIP amount."}}, 200)
    start = parse_date(f.get("start_date"), today_ist())
    step_up = to_decimal(f.get("step_up_pct"), ZERO)
    _plan, s = sip_svc.create_plan(
        holding_id=h.id, amount=amount, start_date=start,
        step_up_pct=step_up, account_id=f.get("account_id", type=int))
    db.session.commit()
    if s["count"]:
        msg = f"SIP set up — backfilled {s['count']} installment(s), {fmt_inr(s['invested'], paise=False)} invested."
    else:
        msg = f"SIP scheduled — first installment on {start.strftime('%d %b %Y')}."
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": msg}})


@bp.route("/mf/sip/<int:plan_id>/stop", methods=["POST"])
def mf_sip_stop(plan_id):
    p = db.session.get(SIPPlan, plan_id) or abort(404)
    sip_svc.stop_plan(p)
    db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "SIP stopped — past investments kept."}})


@bp.route("/mf/sip/<int:plan_id>/delete", methods=["POST"])
def mf_sip_delete(plan_id):
    p = db.session.get(SIPPlan, plan_id) or abort(404)
    sip_svc.delete_plan(p)
    db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "SIP removed — past investments kept."}})


# ---- Gold ------------------------------------------------------------------
@bp.route("/gold/txn/save", methods=["POST"])
def gold_txn_save():
    from ..models import GoldHolding, GoldTransaction
    holding = GoldHolding.query.first()
    if holding is None:
        holding = GoldHolding()
        db.session.add(holding)
        db.session.flush()
    f = request.form
    ppg = money(f.get("price_per_gram"))
    amount = money(f.get("amount"))
    grams = to_decimal(f.get("grams"), ZERO)
    # The form asks for the rupee amount now; derive grams = amount ÷ price.
    # (Fall back to grams × price for older/backfill callers that send grams.)
    if amount > 0 and ppg > 0:
        grams = quantize4(amount / ppg)
    elif grams > 0 and ppg > 0:
        amount = money(grams * ppg)
    if amount <= 0 or ppg <= 0:
        return _trigger({"steward-toast": {"kind": "error", "message": "Enter amount and price."}}, 200)
    gtype = f.get("type") if f.get("type") in ("buy", "sell") else "buy"
    t = GoldTransaction(holding_id=holding.id, date=parse_date(f.get("date"), today_ist()),
                        type=gtype, grams=grams, price_per_gram=ppg, amount=amount,
                        provider=(f.get("provider") or holding.provider))
    db.session.add(t)
    db.session.flush()
    invest_link.sync_cash(
        "gold", t.id, account_id=f.get("account_id", type=int),
        amount=amount, on=t.date, flow="in" if gtype == "sell" else "out",
        note="Digital gold")
    db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Gold entry added."}})


@bp.route("/gold/txn/<int:txn_id>/delete", methods=["POST"])
def gold_txn_delete(txn_id):
    from ..models import GoldTransaction
    t = db.session.get(GoldTransaction, txn_id) or abort(404)
    invest_link.unlink_cash("gold", t.id)
    db.session.delete(t); db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Deleted."}})


@bp.route("/gold/refresh", methods=["POST"])
def gold_refresh():
    from ..services import gold as gold_svc, market as market_svc
    market_svc.refresh_usdinr()
    ok = gold_svc.refresh_gold_rate()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success" if ok else "warn",
                                       "message": "Gold rate updated." if ok else "Couldn't fetch — kept last rate."}})


# ---- Deposits --------------------------------------------------------------
@bp.route("/deposit/save", methods=["POST"])
def deposit_save():
    from ..models import Deposit, DEPOSIT_KINDS
    f = request.form
    did = f.get("id")
    d = db.session.get(Deposit, int(did)) if did and did.isdigit() else Deposit()
    d.kind = f.get("kind") if f.get("kind") in DEPOSIT_KINDS else "FD"
    d.bank = (f.get("bank") or "").strip()
    d.principal = money(f.get("principal")) if d.kind == "FD" else ZERO
    d.installment = money(f.get("installment")) if d.kind == "RD" else ZERO
    d.interest_rate = to_decimal(f.get("interest_rate"), ZERO)
    d.compounding = f.get("compounding") or "quarterly"
    d.start_date = parse_date(f.get("start_date"), today_ist())
    d.tenure_months = f.get("tenure_months", type=int) or 12
    d.note = (f.get("note") or "").strip()
    is_new = not (did and did.isdigit())
    if is_new:
        db.session.add(d)
    db.session.flush()
    # Re-sync cash on create, or on edit when an account is chosen. A blank
    # account on edit is left alone so we never silently drop an existing link;
    # unlink by deleting the deposit instead.
    account_id = f.get("account_id", type=int)
    if is_new or account_id:
        invest_link.sync_deposit_cash(d, account_id)
    db.session.commit()
    flash("Deposit saved.", "success")
    return redirect(url_for("savings.index", tab="deposits"))


@bp.route("/deposit/<int:dep_id>/close", methods=["POST"])
def deposit_close(dep_id):
    """Close a deposit early: deposit its current value into the bank account."""
    from ..models import Deposit
    from ..services import deposit_actions
    from ..services.calculators import deposit_summary
    d = db.session.get(Deposit, dep_id) or abort(404)
    if d.closed_on:
        flash("Deposit is already closed.", "error")
        return redirect(url_for("savings.index", tab="deposits"))
    f = request.form
    on = parse_date(f.get("on"), today_ist())
    proceeds = money(f.get("proceeds")) if f.get("proceeds") else deposit_summary(d, on)["accrued_value"]
    account_id = f.get("account_id", type=int) or deposit_actions.bank_account_for(d)
    deposit_actions.close_deposit(d, on=on, proceeds=proceeds, account_id=account_id)
    db.session.commit()
    flash(f"Deposit closed — {fmt_inr(proceeds, paise=False)} deposited.", "success")
    return redirect(url_for("savings.index", tab="deposits"))


@bp.route("/deposit/<int:dep_id>/delete", methods=["POST"])
def deposit_delete(dep_id):
    from ..models import Deposit
    d = db.session.get(Deposit, dep_id) or abort(404)
    # A closed deposit's cash movements (contributions + the close credit) are
    # historical facts — keep them. An active deposit unlinks its cash on delete.
    if not d.closed_on:
        invest_link.unlink_cash("deposit", d.id)
    invest_link._remove_invest_rules("deposit", d.id)
    db.session.delete(d); db.session.commit()
    flash("Deposit removed.", "success")
    return redirect(url_for("savings.index", tab="deposits"))


# ---- EPF -------------------------------------------------------------------
@bp.route("/epf/entry/save", methods=["POST"])
def epf_entry_save():
    from ..models import EPFAccount, EPFEntry
    f = request.form
    account = EPFAccount.query.first()
    if account is None:
        account = EPFAccount(name="EPF")
        db.session.add(account); db.session.flush()
    e = EPFEntry(account_id=account.id,
                 month=parse_date((f.get("month") or "") + "-01" if f.get("month") and len(f.get("month")) == 7 else f.get("month"), today_ist().replace(day=1)),
                 entry_type="contribution",
                 employee_share=money(f.get("employee_share")),
                 employer_share=money(f.get("employer_share")))
    db.session.add(e)
    db.session.flush()
    # Optional cash link: only the employee share is your money. EPF is usually
    # deducted from salary before it reaches your account, so leaving "Paid from"
    # blank (asset-only) is the norm — pick an account only if you pay it yourself.
    invest_link.sync_cash(
        "epf", e.id, account_id=f.get("account_id", type=int),
        amount=e.employee_share, on=e.month, flow="out", note="EPF contribution")
    db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "EPF entry added."}})


@bp.route("/epf/entry/<int:entry_id>/delete", methods=["POST"])
def epf_entry_delete(entry_id):
    from ..models import EPFEntry
    e = db.session.get(EPFEntry, entry_id) or abort(404)
    invest_link.unlink_cash("epf", e.id)
    db.session.delete(e); db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Deleted."}})


@bp.route("/epf/interest", methods=["POST"])
def epf_interest():
    from ..models import EPFAccount
    from ..services import epf as epf_svc
    account = EPFAccount.query.first()
    if account is None:
        return _trigger({"steward-toast": {"kind": "error", "message": "Add EPF entries first."}}, 200)
    e = epf_svc.add_interest_entry(account)
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": f"Credited interest {e.interest_amount}."}})


# ---- Stock -----------------------------------------------------------------
@bp.route("/stock/save", methods=["POST"])
def stock_save():
    from ..models import StockHolding, StockTransaction
    f = request.form
    ticker = (f.get("ticker") or "").strip().upper()
    if not ticker:
        return _trigger({"steward-toast": {"kind": "error", "message": "Enter a ticker."}}, 200)
    h = StockHolding.query.filter_by(ticker=ticker).first()
    if h is None:
        h = StockHolding(ticker=ticker, name=(f.get("name") or "").strip())
        db.session.add(h); db.session.flush()
    if f.get("qty") and f.get("price_usd"):
        t = StockTransaction(holding_id=h.id, date=parse_date(f.get("date"), today_ist()),
                             qty=to_decimal(f.get("qty"), ZERO), price_usd=money(f.get("price_usd")))
        db.session.add(t)
        db.session.flush()
        # Optional cash link: convert the USD cost to INR at the current rate.
        from ..services import market as market_svc
        amount_inr = money(t.qty * t.price_usd * market_svc.usdinr())
        invest_link.sync_cash(
            "stock", t.id, account_id=f.get("account_id", type=int),
            amount=amount_inr, on=t.date, flow="out",
            note=f"{h.ticker} · {t.qty} @ ${t.price_usd}")
    db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Stock lot added."}})


@bp.route("/stock/txn/<int:txn_id>/delete", methods=["POST"])
def stock_txn_delete(txn_id):
    from ..models import StockTransaction
    t = db.session.get(StockTransaction, txn_id) or abort(404)
    invest_link.unlink_cash("stock", t.id)
    db.session.delete(t); db.session.commit()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Deleted."}})


@bp.route("/stock/refresh", methods=["POST"])
def stock_refresh():
    from ..services import market as market_svc
    market_svc.refresh_usdinr()
    market_svc.refresh_stock_prices()
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": "Stock prices updated."}})


def _trigger(triggers, status=204):
    resp = make_response("", status)
    resp.headers["HX-Trigger"] = json.dumps(triggers)
    return resp

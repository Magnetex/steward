"""Sinking-fund goals: allocation math, caps, and net-worth cleanup."""
from decimal import Decimal


def _goal(client, name, target):
    client.post("/funds/save", data={"name": name, "icon": "🎯", "target_amount": str(target)})


def _fd_id(app):
    from app.models import Deposit
    return Deposit.query.filter_by(kind="FD").first().id


def test_seed_goals_from_allocations(seeded):
    from app.services.funds import all_fund_statuses
    with seeded.app_context():
        by_name = {s["fund"].name: s for s in all_fund_statuses()}
        assert "Emergency fund" in by_name
        em = by_name["Emergency fund"]
        assert len(em["allocs"]) == 2                 # FD slice + cash slice
        assert em["saved"] > 0
        assert 0 <= em["pct"] <= 100
        assert em["target"] == Decimal("500000.00")


def test_create_goal_makes_no_account(seeded):
    from app.models import SinkingFund, Account
    client = seeded.test_client()
    with seeded.app_context():
        n_acc = Account.query.count()
    client.post("/funds/save", data={"name": "Vacation", "icon": "🏖️", "target_amount": "60000"})
    with seeded.app_context():
        assert Account.query.count() == n_acc          # no envelope account created
        assert SinkingFund.query.filter_by(name="Vacation").first() is not None


def test_allocate_caps_at_target(seeded):
    from app.models import SinkingFund, FundAllocation
    client = seeded.test_client()
    _goal(client, "Small goal", 10000)
    with seeded.app_context():
        fid = SinkingFund.query.filter_by(name="Small goal").first().id
        fd_id = _fd_id(seeded)
    # earmark 25000 toward a 10000 goal -> clamped to the 10000 remaining
    r = client.post("/funds/allocate", data={"fund_id": fid, "source": f"deposit:{fd_id}", "amount": "25000"})
    assert r.status_code == 204
    with seeded.app_context():
        allocs = FundAllocation.query.filter_by(fund_id=fid).all()
        assert len(allocs) == 1 and allocs[0].amount == Decimal("10000.00")
    # goal is now full -> a further earmark is a no-op (warn), no new row
    client.post("/funds/allocate", data={"fund_id": fid, "source": f"deposit:{fd_id}", "amount": "5000"})
    with seeded.app_context():
        assert FundAllocation.query.filter_by(fund_id=fid).count() == 1


def test_allocate_caps_at_available(seeded):
    from app.models import SinkingFund, FundAllocation, Account
    from app.services import funds as fsvc
    client = seeded.test_client()
    _goal(client, "Big goal", 10000000)       # target so large the goal cap never binds
    with seeded.app_context():
        fid = SinkingFund.query.filter_by(name="Big goal").first().id
        cash_id = Account.query.filter_by(type="cash").first().id
        avail = fsvc.available_to_allocate("cash", cash_id)
    assert avail > 0
    client.post("/funds/allocate", data={"fund_id": fid, "source": f"cash:{cash_id}", "amount": str(avail)})
    with seeded.app_context():
        assert fsvc.available_to_allocate("cash", cash_id) == Decimal("0.00")
        # fully earmarked now -> another earmark is refused
        client.post("/funds/allocate", data={"fund_id": fid, "source": f"cash:{cash_id}", "amount": "1000"})
        rows = FundAllocation.query.filter_by(fund_id=fid, source_kind="cash", source_ref_id=cash_id).all()
        assert len(rows) == 1 and rows[0].amount == avail


def test_unallocate_releases(seeded):
    from app.extensions import db
    from app.models import SinkingFund, FundAllocation
    from app.services.funds import fund_status
    client = seeded.test_client()
    _goal(client, "Rel goal", 100000)
    with seeded.app_context():
        fid = SinkingFund.query.filter_by(name="Rel goal").first().id
        fd_id = _fd_id(seeded)
    client.post("/funds/allocate", data={"fund_id": fid, "source": f"deposit:{fd_id}", "amount": "5000"})
    with seeded.app_context():
        aid = FundAllocation.query.filter_by(fund_id=fid).first().id
        assert fund_status(db.session.get(SinkingFund, fid))["saved"] == Decimal("5000.00")
    client.post(f"/funds/allocation/{aid}/delete")
    with seeded.app_context():
        assert FundAllocation.query.filter_by(fund_id=fid).count() == 0


def test_networth_has_no_funds_bucket(seeded):
    from app.services import networth as nw
    with seeded.app_context():
        buckets = nw.current_buckets()
        assert "funds" not in buckets
        assert set(buckets) == {"cash_bank", "mf", "gold", "deposits", "epf", "stock"}


def test_spend_goal_redeems_records_and_archives(seeded):
    from app.extensions import db
    from app.models import SinkingFund, FundAllocation, Transaction, Account, Category
    from app.services import funds as fsvc, networth as nw
    with seeded.app_context():
        em = SinkingFund.query.filter_by(name="Emergency fund").first()
        alloc_ids = [a.id for a in em.allocations]     # FD slice + cash slice
        hdfc = Account.query.filter_by(name="HDFC Savings").first()
        cat = Category.query.filter_by(kind="expense").first()
        nw_before = nw.current_total()

        result = fsvc.spend_goal(
            em, alloc_ids=alloc_ids, proceeds_account_id=hdfc.id,
            expense={"amount": "30000", "category_id": cat.id, "account_id": hdfc.id,
                     "payee": "Test spend", "note": "", "date": None},
            archive=True)

        assert result["archived"] is True
        # the purchase is a real expense
        exp = Transaction.query.filter_by(type="expense", payee="Test spend").first()
        assert exp is not None and exp.amount == Decimal("30000.00")
        # every earmark consumed; goal archived (hidden from the active list)
        assert FundAllocation.query.filter_by(fund_id=em.id).count() == 0
        db.session.refresh(em)
        assert em.is_archived is True
        assert em.name not in [s["fund"].name for s in fsvc.all_fund_statuses()]
        # redemptions are net-worth-neutral -> NW drops by exactly the expense
        assert nw.current_total() == nw_before - Decimal("30000.00")


def test_spend_stock_redemption_is_neutral(seeded):
    from app.extensions import db
    from app.models import SinkingFund, FundAllocation, StockHolding, Account, Transaction
    from app.services import funds as fsvc, networth as nw
    with seeded.app_context():
        stock = StockHolding.query.first()
        hdfc = Account.query.filter_by(name="HDFC Savings").first()
        g = SinkingFund(name="Gadget", target_amount=Decimal("50000"))
        db.session.add(g)
        db.session.flush()
        a = FundAllocation(fund_id=g.id, source_kind="stock", source_ref_id=stock.id,
                           amount=Decimal("50000"))
        db.session.add(a)
        db.session.commit()

        nw_before = nw.current_total()
        fsvc.spend_goal(g, alloc_ids=[a.id], proceeds_account_id=hdfc.id,
                        expense=None, archive=False)
        # a "sell" was recorded and the proceeds credited to cash
        assert Transaction.query.filter_by(invest_kind="stock", flow="in").first() is not None
        # redeeming to cash is net-worth-neutral (within sub-rupee unit rounding)
        assert abs(nw.current_total() - nw_before) <= Decimal("1")


def test_archived_goals_split_from_active(seeded):
    from app.extensions import db
    from app.models import SinkingFund
    from app.services import funds as fsvc
    with seeded.app_context():
        em = SinkingFund.query.filter_by(name="Emergency fund").first()
        em.is_archived = True
        db.session.commit()
        assert em.name not in [s["fund"].name for s in fsvc.all_fund_statuses()]
        assert em.name in [s["fund"].name for s in fsvc.archived_fund_statuses()]


def test_delete_goal_keeps_assets(seeded):
    from app.extensions import db
    from app.models import SinkingFund, FundAllocation, Deposit
    client = seeded.test_client()
    _goal(client, "Temp goal", 50000)
    with seeded.app_context():
        fid = SinkingFund.query.filter_by(name="Temp goal").first().id
        fd_id = _fd_id(seeded)
        n_dep = Deposit.query.count()
    client.post("/funds/allocate", data={"fund_id": fid, "source": f"deposit:{fd_id}", "amount": "5000"})
    client.post(f"/funds/{fid}/delete")
    with seeded.app_context():
        assert db.session.get(SinkingFund, fid) is None
        assert FundAllocation.query.filter_by(fund_id=fid).count() == 0
        assert Deposit.query.count() == n_dep       # the FD itself is untouched

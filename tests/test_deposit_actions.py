"""Deposit close lifecycle: early manual close, auto-close at maturity, the
cash transaction each produces, earmark reassignment, and net-worth neutrality."""
from decimal import Decimal


def _accrued(dep):
    from app.services.calculators import deposit_summary
    return deposit_summary(dep)["accrued_value"]


def test_close_fd_early_deposits_to_bank(seeded):
    from app.extensions import db
    from app.models import Deposit, Transaction
    from app.services import deposit_actions, networth as nw, deposits as dep_svc
    from app.timeutil import today_ist
    with seeded.app_context():
        fd = Deposit.query.filter_by(kind="FD").first()
        nw_before = nw.current_total()
        proceeds = _accrued(fd)
        acct = deposit_actions.bank_account_for(fd)
        deposit_actions.close_deposit(fd, on=today_ist(), proceeds=proceeds, account_id=acct)
        db.session.commit()

        assert fd.closed_on is not None and fd.close_account_id == acct
        # a savings "in" credit transaction was recorded into the bank account
        credit = Transaction.query.filter_by(invest_kind="deposit", invest_ref_id=fd.id,
                                              flow="in").first()
        assert credit is not None and credit.amount == proceeds and credit.account_id == acct
        # the FD is gone from the active deposits / net-worth bucket
        assert all(s["deposit"].id != fd.id for s in dep_svc.all_summaries())
        # net worth unchanged (asset -> cash)
        assert nw.current_total() == nw_before


def test_close_rd_early_deposits_to_bank(seeded):
    from app.extensions import db
    from app.models import Deposit, Transaction
    from app.services import deposit_actions, networth as nw
    from app.timeutil import today_ist
    with seeded.app_context():
        rd = Deposit.query.filter_by(kind="RD").first()
        nw_before = nw.current_total()
        proceeds = _accrued(rd)
        acct = deposit_actions.bank_account_for(rd)
        deposit_actions.close_deposit(rd, on=today_ist(), proceeds=proceeds, account_id=acct)
        db.session.commit()

        assert rd.closed_on is not None
        credit = Transaction.query.filter_by(invest_kind="deposit", invest_ref_id=rd.id,
                                              flow="in").first()
        assert credit is not None and credit.amount == proceeds
        assert nw.current_total() == nw_before


def test_close_matured_auto(seeded):
    from app.extensions import db
    from app.models import Deposit, Transaction
    from app.services import deposit_actions, networth as nw
    from app.timeutil import today_ist, add_months
    from app.money import money
    with seeded.app_context():
        # a matured FD (start 13 months ago, 12-month tenure)
        d = Deposit(kind="FD", bank="ICICI", principal=money(Decimal("50000")),
                    interest_rate=money("7.00"), compounding="quarterly",
                    start_date=add_months(today_ist(), -13), tenure_months=12)
        db.session.add(d)
        db.session.commit()
        nw_before = nw.current_total()

        n = deposit_actions.close_matured()
        assert n >= 1
        db.session.refresh(d)
        assert d.closed_on is not None
        credit = Transaction.query.filter_by(invest_kind="deposit", invest_ref_id=d.id,
                                              flow="in").first()
        assert credit is not None
        assert nw.current_total() == nw_before
        # idempotent: nothing left to auto-close
        assert deposit_actions.close_matured() == 0


def test_close_reassigns_earmarks_to_cash(seeded):
    from app.extensions import db
    from app.models import Deposit, FundAllocation, SinkingFund
    from app.services import deposit_actions, funds as fsvc
    from app.timeutil import today_ist
    with seeded.app_context():
        fd = Deposit.query.filter_by(kind="FD").first()
        em = SinkingFund.query.filter_by(name="Emergency fund").first()
        saved_before = fsvc.fund_status(em)["saved"]
        acct = deposit_actions.bank_account_for(fd)

        deposit_actions.close_deposit(fd, on=today_ist(), proceeds=_accrued(fd), account_id=acct)
        db.session.commit()

        allocs = FundAllocation.query.filter_by(fund_id=em.id).all()
        assert all(a.source_kind != "deposit" for a in allocs)        # no dangling deposit earmark
        assert any(a.source_kind == "cash" and a.source_ref_id == acct for a in allocs)
        # the goal keeps its progress — the earmark now rides the cash it became
        assert fsvc.fund_status(em)["saved"] == saved_before


def test_closed_deposit_is_not_an_allocatable_source(seeded):
    from app.extensions import db
    from app.models import Deposit
    from app.services import deposit_actions, funds as fsvc
    from app.timeutil import today_ist
    with seeded.app_context():
        fd = Deposit.query.filter_by(kind="FD").first()
        deposit_actions.close_deposit(fd, on=today_ist(), proceeds=_accrued(fd),
                                      account_id=deposit_actions.bank_account_for(fd))
        db.session.commit()
        assert fsvc.source_current_value("deposit", fd.id) == Decimal("0")
        assert all(not (s["kind"] == "deposit" and s["ref_id"] == fd.id)
                   for s in fsvc.list_sources())


def test_rd_run_due_stops_after_close(seeded):
    from app.extensions import db
    from app.models import Deposit, Transaction
    from app.services import deposit_actions, rd
    from app.timeutil import today_ist
    with seeded.app_context():
        rd_dep = Deposit.query.filter_by(kind="RD").first()
        deposit_actions.close_deposit(rd_dep, on=today_ist(), proceeds=_accrued(rd_dep),
                                      account_id=deposit_actions.bank_account_for(rd_dep))
        db.session.commit()

        def n_out():
            return Transaction.query.filter_by(invest_kind="deposit",
                                               invest_ref_id=rd_dep.id, flow="out").count()
        before = n_out()
        rd.run_due()
        assert n_out() == before        # no further installments once closed

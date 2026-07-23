"""RD auto-contributions (own engine, off the Recurring page)

Adds:
  * deposit.account_id  — "Paid from" cash account (RD monthly + FD one-shot)
  * deposit.next_run_date — RD's next future installment to debit

Data migration: RDs used to run via a savings RecurringRule (which showed up on
the Recurring page). Adopt those into the new engine by copying the rule's
account onto the deposit, then delete the deposit-linked recurring rules. Their
already-created past installment transactions are left untouched.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deposit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('next_run_date', sa.Date(), nullable=True))

    # Adopt any legacy RD RecurringRules into the deposit, then remove them.
    op.execute(
        "UPDATE deposit SET account_id = ("
        "  SELECT rr.account_id FROM recurring_rule rr"
        "  WHERE rr.invest_kind = 'deposit' AND rr.invest_ref_id = deposit.id LIMIT 1)"
        " WHERE EXISTS ("
        "  SELECT 1 FROM recurring_rule rr"
        "  WHERE rr.invest_kind = 'deposit' AND rr.invest_ref_id = deposit.id)"
    )
    op.execute("DELETE FROM recurring_rule WHERE invest_kind = 'deposit'")


def downgrade():
    with op.batch_alter_table('deposit', schema=None) as batch_op:
        batch_op.drop_column('next_run_date')
        batch_op.drop_column('account_id')

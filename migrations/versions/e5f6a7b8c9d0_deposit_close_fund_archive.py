"""Deposit close lifecycle + sinking-fund archive

Adds:
  * deposit.closed_on / closed_value / close_account_id — a deposit can be closed
    (early manual close, or automatically at maturity): its value is deposited
    back into a cash account and it leaves the net-worth "deposits" bucket.
  * sinking_fund.is_archived — a spent/finished goal is archived (hidden from the
    active list, kept for history).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deposit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('closed_on', sa.Date(), nullable=True))
        # DecimalText renders as String (see migrations/env.py render_item).
        batch_op.add_column(sa.Column('closed_value', sa.String(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('close_account_id', sa.Integer(), nullable=True))

    with op.batch_alter_table('sinking_fund', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_archived', sa.Boolean(), nullable=False,
                                      server_default='0'))


def downgrade():
    with op.batch_alter_table('sinking_fund', schema=None) as batch_op:
        batch_op.drop_column('is_archived')

    with op.batch_alter_table('deposit', schema=None) as batch_op:
        batch_op.drop_column('close_account_id')
        batch_op.drop_column('closed_value')
        batch_op.drop_column('closed_on')

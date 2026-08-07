"""gold txn gst amount

Digital gold is bought GST-inclusive: the bank debits the round figure, and
3% of it is tax rather than metal. Splitting the two lets the holding hold
what was actually bought while the cash side still matches the statement.

Existing rows predate the split and recorded the whole debit as gold, so they
default to no GST — that is what they meant at the time.

The foreign keys autogenerate proposes on `deposit` and `mf_txn` are dropped
from this migration on purpose: they exist in the models but were never
recorded in SQLite, and adding them forces a full batch table rebuild.

Revision ID: f96cfa2b4be6
Revises: bd91f1133943
Create Date: 2026-08-07 16:46:51.359335

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f96cfa2b4be6'
down_revision = 'bd91f1133943'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('gold_txn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('gst_amount', sa.String(), nullable=False,
                                      server_default='0'))


def downgrade():
    with op.batch_alter_table('gold_txn', schema=None) as batch_op:
        batch_op.drop_column('gst_amount')

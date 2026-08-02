"""Keep the SMS account digits on pending imports

Revision ID: bd91f1133943
Revises: e2e36ae743e9
Create Date: 2026-08-03 00:49:53.600811

Autogenerate again proposed foreign keys on `deposit` and `mf_txn`. They
already exist in the models and were simply never recorded in SQLite's
schema; adding them would force a batch rebuild of two tables holding real
data for no behavioural gain. Dropped deliberately, as in e2e36ae743e9.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd91f1133943'
down_revision = 'e2e36ae743e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pending_import', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('account_hint', sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column('counterparty_hint', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('pending_import', schema=None) as batch_op:
        batch_op.drop_column('counterparty_hint')
        batch_op.drop_column('account_hint')

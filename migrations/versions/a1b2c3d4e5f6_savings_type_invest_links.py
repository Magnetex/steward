"""savings transaction type + investment cash-links

Adds:
  * transaction.flow ("out"/"in") — savings direction
  * transaction.invest_kind / invest_ref_id — link a cash movement to the
    investment record it funds or redeems
  * recurring_rule.invest_kind / invest_ref_id — link an auto-created rule
    (e.g. an RD's monthly installment) to its investment

Revision ID: a1b2c3d4e5f6
Revises: d9eccfcbb934
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd9eccfcbb934'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'flow', sa.String(length=3), nullable=False, server_default='out'))
        batch_op.add_column(sa.Column('invest_kind', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('invest_ref_id', sa.Integer(), nullable=True))

    with op.batch_alter_table('recurring_rule', schema=None) as batch_op:
        batch_op.add_column(sa.Column('invest_kind', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('invest_ref_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('recurring_rule', schema=None) as batch_op:
        batch_op.drop_column('invest_ref_id')
        batch_op.drop_column('invest_kind')

    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_column('invest_ref_id')
        batch_op.drop_column('invest_kind')
        batch_op.drop_column('flow')

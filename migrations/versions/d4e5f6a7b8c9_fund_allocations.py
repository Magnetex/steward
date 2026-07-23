"""Sinking funds become goals that earmark existing assets

  * new fund_allocation table (fund earmarks a ₹ slice of a holding/cash)
  * sinking_fund.account_id dropped (funds no longer hold their own money)
  * legacy envelope 'fund' accounts archived (funds are no longer accounts)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fund_allocation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fund_id', sa.Integer(), nullable=False),
        sa.Column('source_kind', sa.String(length=8), nullable=False),
        sa.Column('source_ref_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['fund_id'], ['sinking_fund.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Funds are no longer envelope accounts. Hide any legacy ones.
    op.execute("UPDATE account SET is_archived = 1 WHERE type = 'fund'")

    with op.batch_alter_table('sinking_fund', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(length=200), nullable=True))
        batch_op.drop_column('account_id')


def downgrade():
    with op.batch_alter_table('sinking_fund', schema=None) as batch_op:
        batch_op.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
        batch_op.drop_column('note')

    op.drop_table('fund_allocation')

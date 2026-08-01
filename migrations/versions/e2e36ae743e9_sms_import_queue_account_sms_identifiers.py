"""SMS import queue + account SMS identifiers

Revision ID: e2e36ae743e9
Revises: f6a7b8c9d0e1
Create Date: 2026-08-02 03:26:12.421094

Autogenerate also proposed adding foreign keys to `deposit` and `mf_txn`.
Those constraints already exist in the models and were simply never recorded
in SQLite's schema; adding them would force a full batch rebuild of two
tables holding real data for no behavioural gain. Dropped deliberately.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e2e36ae743e9'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pending_import',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False,
                  server_default='sms'),
        sa.Column('sender', sa.String(length=40), nullable=True),
        sa.Column('body', sa.String(length=1000), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('dedupe_hash', sa.String(length=64), nullable=False),
        sa.Column('bank', sa.String(length=12), nullable=True),
        sa.Column('direction', sa.String(length=6), nullable=True),
        sa.Column('amount', sa.String(), nullable=False),
        sa.Column('txn_date', sa.Date(), nullable=False),
        sa.Column('payee', sa.String(length=120), nullable=True),
        sa.Column('reference', sa.String(length=60), nullable=True),
        sa.Column('stated_balance', sa.String(), nullable=True),
        # NOT NULL boolean needs a server_default for existing rows.
        sa.Column('is_reversal', sa.Boolean(), nullable=False,
                  server_default='0'),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('transfer_account_id', sa.Integer(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('suggested_type', sa.String(length=10), nullable=True),
        sa.Column('duplicate_of_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False,
                  server_default='pending'),
        sa.Column('transaction_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ),
        sa.ForeignKeyConstraint(['category_id'], ['category.id'], ),
        sa.ForeignKeyConstraint(['duplicate_of_id'], ['transaction.id'], ),
        sa.ForeignKeyConstraint(['transaction_id'], ['transaction.id'], ),
        sa.ForeignKeyConstraint(['transfer_account_id'], ['account.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pending_import', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pending_import_dedupe_hash'),
                              ['dedupe_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_pending_import_received_at'),
                              ['received_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_pending_import_status'),
                              ['status'], unique=False)

    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sms_identifiers', sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_column('sms_identifiers')

    with op.batch_alter_table('pending_import', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pending_import_status'))
        batch_op.drop_index(batch_op.f('ix_pending_import_received_at'))
        batch_op.drop_index(batch_op.f('ix_pending_import_dedupe_hash'))

    op.drop_table('pending_import')

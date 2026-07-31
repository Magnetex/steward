"""Fold the grocery_wallet account type into wallet

'Grocery wallet' was a redundant account type — naming the account
'Grocery Wallet' conveys the same thing, so the type is now just 'wallet'.

This is a data-only migration. It matters because grocery_wallet was in
CASH_LIKE_TYPES: leaving a row on the removed type would silently drop that
account out of "available to spend" and out of the cash net-worth bucket.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE account SET type = 'wallet' WHERE type = 'grocery_wallet'")


def downgrade():
    # The original type is unrecoverable — which accounts were grocery wallets
    # is not recorded anywhere after the upgrade. Downgrading leaves them as
    # plain wallets, which is harmless: both are cash-like and spendable.
    pass

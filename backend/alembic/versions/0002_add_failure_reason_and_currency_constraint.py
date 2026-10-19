"""add failure_reason and currency constraint

Revision ID: 0002_failure_reason_currency
Revises: 0001_initial_schema
Create Date: 2026-10-20 12:10:00.000000

Два изменения схемы:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_failure_reason_currency'
down_revision: str | Sequence[str] | None = '0001_initial_schema'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payments',
        sa.Column('failure_reason', sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        'ck_payments_currency',
        'payments',
        "currency IN ('RUB', 'USD', 'EUR')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_payments_currency', 'payments', type_='check')
    op.drop_column('payments', 'failure_reason')

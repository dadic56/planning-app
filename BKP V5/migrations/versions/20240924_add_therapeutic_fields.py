"""add therapeutic part-time fields

Revision ID: 20240924_add_thera
Revises: f10ea08f4fe8
Create Date: 2024-09-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20240924_add_thera'
down_revision = 'f10ea08f4fe8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col['name'] for col in inspector.get_columns('employee')}

    if 'therapeutic_part_time' not in existing_cols:
        op.add_column('employee', sa.Column('therapeutic_part_time', sa.Boolean(), nullable=True))
        op.execute('UPDATE employee SET therapeutic_part_time = 0 WHERE therapeutic_part_time IS NULL')
    else:
        op.execute('UPDATE employee SET therapeutic_part_time = COALESCE(therapeutic_part_time, 0)')

    if 'therapeutic_percent' not in existing_cols:
        op.add_column('employee', sa.Column('therapeutic_percent', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('employee', 'therapeutic_percent')
    op.drop_column('employee', 'therapeutic_part_time')

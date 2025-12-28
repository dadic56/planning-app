"""add allow overtime flag

Revision ID: 20240925_add_allow_overtime
Revises: 20240924_add_thera
Create Date: 2024-09-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20240925_add_allow_overtime'
down_revision = '20240924_add_thera'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col['name'] for col in inspector.get_columns('employee')}
    if 'allow_overtime' not in existing_cols:
        op.add_column('employee', sa.Column('allow_overtime', sa.Boolean(), nullable=True))
        op.execute('UPDATE employee SET allow_overtime = 1 WHERE allow_overtime IS NULL')
    else:
        op.execute('UPDATE employee SET allow_overtime = COALESCE(allow_overtime, 1)')


def downgrade() -> None:
    op.drop_column('employee', 'allow_overtime')

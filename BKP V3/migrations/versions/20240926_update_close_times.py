"""update close times to 19:15

Revision ID: 20240926_update_close_times
Revises: 20240925_add_allow_overtime
Create Date: 2024-09-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20240926_update_close_times'
down_revision = '20240925_add_allow_overtime'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE opening_hours SET close_time='19:15' WHERE close_time='19:30'"))
    conn.execute(sa.text("UPDATE base_shift SET end_time='19:15' WHERE end_time='19:30'"))
    conn.execute(sa.text("UPDATE adjusted_shift SET end_time='19:15' WHERE end_time='19:30'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE opening_hours SET close_time='19:30' WHERE close_time='19:15'"))
    conn.execute(sa.text("UPDATE base_shift SET end_time='19:30' WHERE end_time='19:15'"))
    conn.execute(sa.text("UPDATE adjusted_shift SET end_time='19:30' WHERE end_time='19:15'"))

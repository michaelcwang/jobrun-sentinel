"""phase 2c runtime topology

Revision ID: 0004_phase2c_runtime_topology
Revises: 0003_phase2b_diagnostics
Create Date: 2026-06-20
"""

revision = "0004_phase2c_runtime_topology"
down_revision = "0003_phase2b_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    from app.models import DbSessionSnapshot, JobRunNodeBinding, RuntimeNode, RuntimeNodeMetricSample

    bind = op.get_bind()
    for table in [
        RuntimeNode.__table__,
        RuntimeNodeMetricSample.__table__,
        JobRunNodeBinding.__table__,
        DbSessionSnapshot.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Non-destructive for local MVP environments. Rebuild lower environments
    # from scratch when dropping topology tables is required.
    pass

"""phase 2b diagnostics workbench

Revision ID: 0003_phase2b_diagnostics
Revises: 0002_phase2_connector_schema
Create Date: 2026-06-20
"""

revision = "0003_phase2b_diagnostics"
down_revision = "0002_phase2_connector_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    from app.models import (
        DiagnosticDataQualityCheck,
        DiagnosticEvidence,
        DiagnosticFinding,
        DiagnosticMetric,
        DiagnosticReport,
        DiagnosticRunbookStep,
        GlossaryTerm,
        ReportTemplate,
        RuledOutAlternative,
    )

    bind = op.get_bind()
    for table in [
        DiagnosticReport.__table__,
        DiagnosticFinding.__table__,
        DiagnosticEvidence.__table__,
        DiagnosticMetric.__table__,
        RuledOutAlternative.__table__,
        DiagnosticDataQualityCheck.__table__,
        DiagnosticRunbookStep.__table__,
        GlossaryTerm.__table__,
        ReportTemplate.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Non-destructive for the MVP migration chain. Rebuild lower environments
    # from scratch when dropping diagnostic workbench tables is required.
    pass

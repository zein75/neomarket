"""Enforce casework input invariants in PostgreSQL."""

from alembic import op


revision = "0028_admin_casework_input_constraints"
down_revision = "0027_admin_complaint_queue_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_admin_complaint_source",
        "admin_complaints",
        "source IN ('B2C','SELLER','ADMIN')",
    )
    op.create_check_constraint(
        "ck_admin_complaint_reporter_ref",
        "admin_complaints",
        "reporter_ref ~ '^[a-fA-F0-9]{64}$'",
    )
    op.create_check_constraint(
        "ck_admin_complaint_action_type",
        "admin_complaint_actions",
        "action IN ('ASSIGN','REQUEST_INFO','WARN','TEMP_HOLD','UNPUBLISH','CLOSE','ESCALATE')",
    )
    op.create_check_constraint(
        "ck_admin_complaint_action_reason",
        "admin_complaint_actions",
        "reason_code ~ '^[A-Z][A-Z0-9_]*$'",
    )
    op.create_check_constraint(
        "ck_admin_complaint_action_hash",
        "admin_complaint_actions",
        "request_hash ~ '^[a-f0-9]{64}$'",
    )
    op.create_check_constraint(
        "ck_admin_appeal_claimant_ref",
        "admin_appeals",
        "claimant_ref ~ '^[a-fA-F0-9]{64}$'",
    )
    op.create_check_constraint(
        "ck_admin_appeal_decision_reason",
        "admin_appeal_decisions",
        "reason_code ~ '^[A-Z][A-Z0-9_]*$'",
    )
    op.create_check_constraint(
        "ck_admin_appeal_decision_hash",
        "admin_appeal_decisions",
        "request_hash ~ '^[a-f0-9]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_admin_appeal_decision_hash", "admin_appeal_decisions", type_="check")
    op.drop_constraint("ck_admin_appeal_decision_reason", "admin_appeal_decisions", type_="check")
    op.drop_constraint("ck_admin_appeal_claimant_ref", "admin_appeals", type_="check")
    op.drop_constraint("ck_admin_complaint_action_hash", "admin_complaint_actions", type_="check")
    op.drop_constraint("ck_admin_complaint_action_reason", "admin_complaint_actions", type_="check")
    op.drop_constraint("ck_admin_complaint_action_type", "admin_complaint_actions", type_="check")
    op.drop_constraint("ck_admin_complaint_reporter_ref", "admin_complaints", type_="check")
    op.drop_constraint("ck_admin_complaint_source", "admin_complaints", type_="check")

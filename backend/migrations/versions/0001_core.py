"""Initial eight-table schema, frozen from the approved database design."""

from pathlib import Path

from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade():
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_constraint("fk_versions_active_import", "document_versions", type_="foreignkey")
    for table in (
        "message_citations",
        "chat_messages",
        "chat_sessions",
        "chunks",
        "document_contents",
        "processing_jobs",
        "document_versions",
        "documents",
    ):
        op.drop_table(table)
    # vector can be used by another schema; do not uninstall the extension on downgrade.

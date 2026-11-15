"""Allow validated PNG/JPEG originals without changing existing document identities."""

from alembic import op
from sqlalchemy import text

revision = "0003_image_documents"
down_revision = "0002_file_fingerprint"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("document_versions_format_check", "document_versions", type_="check")
    op.create_check_constraint(
        "document_versions_format_check",
        "document_versions",
        "format IN ('pdf', 'docx', 'md', 'png', 'jpg')",
    )


def downgrade():
    if op.get_bind().scalar(
        text("SELECT EXISTS(SELECT 1 FROM document_versions WHERE format IN ('png','jpg'))")
    ):
        raise RuntimeError("Image documents exist; preserve them before downgrading")
    op.drop_constraint("document_versions_format_check", "document_versions", type_="check")
    op.create_check_constraint(
        "document_versions_format_check",
        "document_versions",
        "format IN ('pdf', 'docx', 'md')",
    )

"""
Index file fingerprints for checks across the whole library.
为全库文件指纹检查建立索引
"""

from alembic import op

revision = "0002_file_fingerprint"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_versions_file_sha256", "document_versions", ["file_sha256"])


def downgrade():
    op.drop_index("ix_versions_file_sha256", table_name="document_versions")

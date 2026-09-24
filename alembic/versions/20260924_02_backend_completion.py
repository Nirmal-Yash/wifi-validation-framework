from alembic import op
import sqlalchemy as sa

revision = "20260924_02"
down_revision = "20260924_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    additions = {
        "test_results": {
            "failure_class": sa.String(),
            "failure_reason": sa.Text(),
            "execution_pid": sa.Integer(),
        },
        "artifacts": {
            "failure_class": sa.String(),
            "failure_reason": sa.Text(),
            "execution_pid": sa.Integer(),
        },
    }

    for table, columns in additions.items():
        existing = {item["name"] for item in inspector.get_columns(table)}
        for name, column_type in columns.items():
            if name not in existing:
                op.add_column(table, sa.Column(name, column_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, columns in (
        ("artifacts", ("execution_pid", "failure_reason", "failure_class")),
        ("test_results", ("execution_pid", "failure_reason", "failure_class")),
    ):
        existing = {item["name"] for item in inspector.get_columns(table)}
        for name in columns:
            if name in existing:
                op.drop_column(table, name)

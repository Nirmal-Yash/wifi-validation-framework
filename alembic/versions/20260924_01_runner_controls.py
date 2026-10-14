from alembic import op
import sqlalchemy as sa
revision="20260924_01"
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    bind=op.get_bind()
    inspector=sa.inspect(bind)
    cols={c["name"] for c in inspector.get_columns("runs")}
    for name,typ in (("failure_class",sa.String()),("failure_reason",sa.Text()),("execution_pid",sa.Integer())):
        if name not in cols: op.add_column("runs",sa.Column(name,typ,nullable=True))
    tables=set(inspector.get_table_names())
    if "release_waivers" not in tables:
        op.create_table("release_waivers",
            sa.Column("waiver_id",sa.String(),primary_key=True),
            sa.Column("scope",sa.String(),nullable=False),
            sa.Column("target_id",sa.String(),nullable=False),
            sa.Column("issue_code",sa.String(),nullable=False),
            sa.Column("reason",sa.Text(),nullable=False),
            sa.Column("created_by",sa.String(),nullable=False),
            sa.Column("created_at",sa.String(),nullable=False),
            sa.Column("expires_at",sa.String(),nullable=True),
            sa.Column("audit_reference",sa.String(),nullable=False),
            sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.text("1")))
        op.create_index("idx_waivers_target","release_waivers",["target_id","active","expires_at"])
def downgrade():
    bind=op.get_bind()
    inspector=sa.inspect(bind)
    if "release_waivers" in inspector.get_table_names():op.drop_table("release_waivers")
    cols={c["name"] for c in inspector.get_columns("runs")}
    for name in ("execution_pid","failure_reason","failure_class"):
        if name in cols:op.drop_column("runs",name)

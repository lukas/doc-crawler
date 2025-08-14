"""Initial schema

Revision ID: 0001
Revises: 
Create Date: 2025-01-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create files table
    op.create_table('files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('sha', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('lang', sa.Text(), default='en'),
        sa.Column('last_seen_commit', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), default='active'),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path')
    )
    
    # Create analysis_runs table
    op.create_table('analysis_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('commit_sha', sa.Text(), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('finished_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('llm_token_in', sa.BIGINT(), default=0),
        sa.Column('llm_token_out', sa.BIGINT(), default=0),
        sa.Column('llm_cost_estimate', sa.NUMERIC(), default=0),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create rules table
    op.create_table('rules',
        sa.Column('rule_code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('default_severity', sa.Text(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('rule_code')
    )
    
    # Create issues table
    op.create_table('issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('rule_code', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('snippet', sa.Text(), nullable=True),
        sa.Column('line_start', sa.Integer(), nullable=True),
        sa.Column('line_end', sa.Integer(), nullable=True),
        sa.Column('col_start', sa.Integer(), nullable=True),
        sa.Column('col_end', sa.Integer(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('proposed_snippet', sa.Text(), nullable=True),
        sa.Column('suggested_patch', sa.Text(), nullable=True),
        sa.Column('citations', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.NUMERIC(), nullable=True),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('can_auto_apply', sa.Boolean(), nullable=False, default=False),
        sa.Column('state', sa.String(length=20), default='open'),
        sa.Column('first_seen_run_id', sa.Integer(), nullable=False),
        sa.Column('last_seen_run_id', sa.Integer(), nullable=False),
        sa.Column('pr_state', sa.String(length=20), default='none'),
        sa.Column('pr_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['files.id'], ),
        sa.ForeignKeyConstraint(['first_seen_run_id'], ['analysis_runs.id'], ),
        sa.ForeignKeyConstraint(['last_seen_run_id'], ['analysis_runs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create unique index on issues
    op.create_index('idx_unique_issue', 'issues', ['file_id', 'rule_code', 'line_start', 'title'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_unique_issue', table_name='issues')
    op.drop_table('issues')
    op.drop_table('rules')
    op.drop_table('analysis_runs')
    op.drop_table('files')
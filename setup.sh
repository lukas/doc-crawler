#!/bin/bash
set -e

echo "🚀 Setting up DocsQA system..."

# Check if we're in the right directory
if [ ! -f "docsqa/backend/app.py" ]; then
    echo "❌ Please run this script from the root directory (where this setup.sh is located)"
    exit 1
fi

# Install system dependencies (if running as root in container)
if [ "$(id -u)" = "0" ]; then
    echo "🔧 Installing system dependencies..."
    apt-get update
    apt-get install -y git curl build-essential python3-dev python3-pip python3-venv
    echo "✅ System dependencies installed"
fi

# Set up Python environment
cd docsqa

echo "🐍 Setting up Python environment..."

# Handle virtual environment for non-container environments
if [ -z "$CONTAINER" ] && [ "$(id -u)" != "0" ]; then
    echo "📦 Setting up virtual environment..."
    
    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
        echo "✅ Created virtual environment"
    fi
    
    # Activate virtual environment
    source .venv/bin/activate
    echo "✅ Activated virtual environment"
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install dependencies
    pip install -r backend/requirements.txt
else
    # In container or as root, install system-wide
    echo "📦 Installing Python dependencies system-wide..."
    if [ "$(id -u)" = "0" ]; then
        # Running as root (container), can install system-wide
        pip install --break-system-packages -r backend/requirements.txt
    else
        # Not root but in container environment
        pip install --user -r backend/requirements.txt
    fi
fi

echo "✅ Python dependencies installed"

# Set environment variables for development
export PYTHONPATH="${PWD}/backend"
export DATABASE_URL=${DATABASE_URL:-"sqlite:///dev.db"}

echo "🗃️  Setting up database..."

# Determine which Python to use
PYTHON_CMD="python3"
if [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
fi

# Initialize database
$PYTHON_CMD -c "
import sys
sys.path.insert(0, 'backend')
from core.db import init_db
init_db()
print('✅ Database initialized')
"

echo "🛠️  Seeding default rules..."
# Seed rules
$PYTHON_CMD -c "
import sys
sys.path.insert(0, 'backend')
import asyncio
from core.db import db
from core.models import Rule

default_rules = [
    {'rule_code': 'LINK_404', 'name': 'Broken Link (404)', 'category': 'links', 'default_severity': 'high', 'config': {}},
    {'rule_code': 'LINK_TIMEOUT', 'name': 'Link Timeout', 'category': 'links', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'SDKVER_OLD', 'name': 'Outdated SDK Version', 'category': 'versions', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'SDKVER_MAJOR', 'name': 'Major Version Behind', 'category': 'versions', 'default_severity': 'high', 'config': {}},
    {'rule_code': 'API_UNKNOWN', 'name': 'Unknown API Symbol', 'category': 'api', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'API_DEPRECATED', 'name': 'Deprecated API', 'category': 'api', 'default_severity': 'high', 'config': {}},
    {'rule_code': 'CLI_UNKNOWN', 'name': 'Unknown CLI Command', 'category': 'cli', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'CLI_DEPRECATED', 'name': 'Deprecated CLI Command', 'category': 'cli', 'default_severity': 'high', 'config': {}},
    {'rule_code': 'STYLE_NO_H1', 'name': 'Missing H1 Heading', 'category': 'style', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'STYLE_MULTIPLE_H1', 'name': 'Multiple H1 Headings', 'category': 'style', 'default_severity': 'low', 'config': {}},
    {'rule_code': 'STYLE_IMG_NO_ALT', 'name': 'Image Missing Alt Text', 'category': 'style', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'STYLE_TERMINOLOGY', 'name': 'Non-canonical Terminology', 'category': 'style', 'default_severity': 'low', 'config': {}},
    {'rule_code': 'LLM_SPELL', 'name': 'Spelling Error (LLM)', 'category': 'llm', 'default_severity': 'low', 'config': {}},
    {'rule_code': 'LLM_GRAMMAR', 'name': 'Grammar Issue (LLM)', 'category': 'llm', 'default_severity': 'low', 'config': {}},
    {'rule_code': 'LLM_CLARITY', 'name': 'Clarity Improvement (LLM)', 'category': 'llm', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'LLM_ACCURACY', 'name': 'Accuracy Issue (LLM)', 'category': 'llm', 'default_severity': 'high', 'config': {}},
    {'rule_code': 'LLM_CONSISTENCY', 'name': 'Consistency Issue (LLM)', 'category': 'llm', 'default_severity': 'medium', 'config': {}},
    {'rule_code': 'LLM_UNSURE', 'name': 'Uncertain Issue (LLM)', 'category': 'llm', 'default_severity': 'low', 'config': {}}
]

created_count = 0
with db.get_session() as session:
    for rule_data in default_rules:
        existing = session.query(Rule).filter(Rule.rule_code == rule_data['rule_code']).first()
        if not existing:
            rule = Rule(**rule_data)
            session.add(rule)
            created_count += 1
    session.commit()

print(f'✅ Seeded {created_count} default rules')
"

echo "📂 Creating sample file records..."
$PYTHON_CMD -c "
import sys
sys.path.insert(0, 'backend')
from core.db import db
from core.models import File
from datetime import datetime

sample_files = [
    {'path': 'guides/quickstart.md', 'title': 'Quickstart Guide', 'sha': 'abc123', 'last_seen_commit': 'main', 'status': 'active'},
    {'path': 'guides/tracking/intro.md', 'title': 'Experiment Tracking Introduction', 'sha': 'def456', 'last_seen_commit': 'main', 'status': 'active'},
    {'path': 'guides/artifacts/intro.mdx', 'title': 'Artifacts Overview', 'sha': 'ghi789', 'last_seen_commit': 'main', 'status': 'active'}
]

created_count = 0
with db.get_session() as session:
    for file_data in sample_files:
        existing = session.query(File).filter(File.path == file_data['path']).first()
        if not existing:
            file_record = File(**file_data)
            session.add(file_record)
            created_count += 1
    session.commit()

print(f'✅ Created {created_count} sample files')
"

echo "🏃 Creating sample analysis run..."
$PYTHON_CMD -c "
import sys
sys.path.insert(0, 'backend')
from core.db import db
from core.models import AnalysisRun, RunSource, RunStatus
from datetime import datetime

with db.get_session() as session:
    # Check if we already have runs
    existing_run = session.query(AnalysisRun).first()
    if not existing_run:
        run = AnalysisRun(
            commit_sha='abcdef123456',
            source=RunSource.MANUAL,
            status=RunStatus.SUCCESS,
            started_at=datetime.now(),
            finished_at=datetime.now(),
            stats={'files_analyzed': 3, 'issues_found': 0}
        )
        session.add(run)
        session.commit()
        print('✅ Created sample analysis run')
    else:
        print('✅ Sample run already exists')
"

# Create data directory for repo clones
echo "📁 Creating data directories..."
mkdir -p /data
chmod 777 /data
echo "✅ Data directories created"

echo ""
echo "🎉 DocsQA setup completed successfully!"
echo ""
echo "📋 Next steps:"
echo "  1. Set environment variables (optional):"
echo "     export OPENAI_API_KEY=\"your-openai-key\""
echo "     export GITHUB_APP_ID=\"your-github-app-id\""
echo ""  
echo "  2. Start the API server:"
echo "     cd docsqa/backend && python app.py"
echo ""
echo "  3. Run analysis:"
echo "     cd docsqa && python -m crawler.run_analysis --source manual"
echo ""
echo "  4. Access the API:"
echo "     http://localhost:8080/docs (API documentation)"
echo "     http://localhost:8080/health (health check)"
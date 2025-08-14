#!/bin/bash
set -e

echo "🌱 Seeding DocsQA database with development data..."

# Check if we're in the right directory
if [ ! -f "backend/app.py" ]; then
    echo "❌ Please run this script from the docsqa root directory"
    exit 1
fi

# Set environment variables for development
export DATABASE_URL=${DATABASE_URL:-"sqlite:///dev.db"}
export PYTHONPATH="${PWD}/backend"

cd backend

echo "📦 Installing dependencies..."

# Check if we're in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Not in a virtual environment. Creating one..."
    
    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
        echo "✅ Created virtual environment at .venv"
    fi
    
    # Activate virtual environment
    source .venv/bin/activate
    echo "✅ Activated virtual environment"
    
    # Upgrade pip
    pip install --upgrade pip
fi

# Install dependencies
pip install -r requirements.txt

echo "🗃️  Setting up database..."
# Run migrations
python -c "
from core.db import init_db
init_db()
print('Database initialized')
"

echo "🛠️  Seeding default rules..."
python -c "
import asyncio
from core.db import db
from api.rules import seed_default_rules

async def seed():
    with db.get_session() as session:
        # Mock request object
        class MockDB:
            def query(self, model):
                return session.query(model)
            def add(self, obj):
                return session.add(obj)
            def commit(self):
                return session.commit()
        
        result = await seed_default_rules(db=MockDB())
        print(f'Seeded rules: {result}')

asyncio.run(seed())
"

echo "📂 Creating sample file records..."
python -c "
from core.db import db
from core.models import File
from datetime import datetime

with db.get_session() as session:
    sample_files = [
        File(
            path='guides/quickstart.md',
            title='Quickstart Guide',
            sha='abc123',
            last_seen_commit='main'
        ),
        File(
            path='guides/tracking/intro.md', 
            title='Experiment Tracking Introduction',
            sha='def456',
            last_seen_commit='main'
        ),
        File(
            path='guides/artifacts/intro.mdx',
            title='Artifacts Overview',
            sha='ghi789',
            last_seen_commit='main'
        )
    ]
    
    for file in sample_files:
        existing = session.query(File).filter(File.path == file.path).first()
        if not existing:
            session.add(file)
    
    session.commit()
    print('✅ Created sample files')
"

echo "🏃 Creating sample analysis run..."
python -c "
from core.db import db
from core.models import AnalysisRun, RunSource, RunStatus
from datetime import datetime

with db.get_session() as session:
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
    print('✅ Created sample run')
"

echo "✅ Development database seeded successfully!"
echo ""
echo "🚀 You can now start the development server:"
echo "   cd backend && python app.py"
echo ""
echo "📖 API docs will be available at: http://localhost:8080/docs"
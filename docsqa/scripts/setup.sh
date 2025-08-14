#!/bin/bash
set -e

echo "🚀 Setting up DocsQA development environment..."

# Check if we're in the right directory
if [ ! -f "backend/app.py" ]; then
    echo "❌ Please run this script from the docsqa root directory"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
REQUIRED_VERSION="3.11"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "⚠️  Python $REQUIRED_VERSION or higher is required (found $PYTHON_VERSION)"
    echo "Please install Python $REQUIRED_VERSION or higher"
    exit 1
fi

echo "✅ Python version: $PYTHON_VERSION"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
    echo "✅ Virtual environment created at .venv"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📚 Installing dependencies..."
pip install -r backend/requirements.txt

echo "✅ Setup complete!"
echo ""
echo "To activate the environment in your current shell, run:"
echo "  source .venv/bin/activate"
echo ""
echo "Then you can run:"
echo "  ./scripts/dev_seed.sh    # Seed database"
echo "  ./scripts/run_once.sh    # Run analysis"
echo ""
echo "Or run the scripts directly (they'll auto-activate the environment)"
#!/bin/bash
set -e

echo "🔍 Running DocsQA analysis..."

# Check if we're in the right directory
if [ ! -f "backend/crawler/run_analysis.py" ]; then
    echo "❌ Please run this script from the docsqa root directory"
    exit 1
fi

# Set environment variables
export PYTHONPATH="${PWD}/backend"
export DATABASE_URL=${DATABASE_URL:-"sqlite:///dev.db"}

# Parse command line arguments
SOURCE="manual"
NO_LLM=false
DEBUG=false
COMMIT=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --commit)
      COMMIT="$2"
      shift 2
      ;;
    --no-llm)
      NO_LLM=true
      shift
      ;;
    --debug)
      DEBUG=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --source SOURCE    Run source (manual, scheduled, webhook) [default: manual]"
      echo "  --commit SHA       Specific commit SHA to analyze"
      echo "  --no-llm          Disable LLM analysis"
      echo "  --debug           Enable debug logging"
      echo "  -h, --help        Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

# Check for required environment variables if LLM is enabled
if [ "$NO_LLM" = false ]; then
    if [ -z "$OPENAI_API_KEY" ]; then
        echo "⚠️  Warning: OPENAI_API_KEY not set, running with --no-llm"
        NO_LLM=true
    fi
fi

# Build command
CMD="python backend/crawler/run_analysis.py --source $SOURCE"

if [ "$NO_LLM" = true ]; then
    CMD="$CMD --no-llm"
    echo "🤖 LLM analysis disabled"
fi

if [ "$DEBUG" = true ]; then
    CMD="$CMD --debug"
    echo "🐛 Debug logging enabled"
fi

if [ -n "$COMMIT" ]; then
    CMD="$CMD --commit $COMMIT"
    echo "📝 Analyzing specific commit: $COMMIT"
fi

echo "🚀 Starting analysis..."
echo "   Source: $SOURCE"
echo "   LLM: $([ "$NO_LLM" = true ] && echo "disabled" || echo "enabled")"
echo ""

# Run the analysis
$CMD

echo ""
echo "✅ Analysis completed!"
echo ""
echo "📊 View results at: http://localhost:8080/docs"
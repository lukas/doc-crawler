# DocsQA - Documentation Quality Assurance System

A Python-based system that automatically scans W&B documentation for issues like typos, grammar errors, broken links, and outdated content, then proposes fixes via AI-powered suggestions.

## Key Features

- **Multi-analyzer Pipeline**: Detects broken links, outdated versions, deprecated APIs, style issues
- **LLM-Powered Improvements**: Uses GPT-4 for clarity, grammar, and accuracy suggestions with citations
- **Automated PR Creation**: Creates GitHub PRs with verified fixes for review
- **Safety Guardrails**: Validates patches before auto-applying changes
- **REST API**: Full FastAPI backend with issue management and workflow controls

## Quick Commands

```bash
# Setup and run analysis
./setup.sh
uv run docsqa-analyze --source manual --no-llm

# Start API server
uv run docsqa-server

# Run with LLM improvements (requires OPENAI_API_KEY)
uv run docsqa-analyze --source manual
```

## Architecture

- **Backend**: Python + FastAPI + SQLAlchemy + Alembic
- **Analysis**: Rule-based analyzers + LLM quality engine
- **Storage**: PostgreSQL (SQLite in dev)
- **Search**: FAISS embeddings for context retrieval
- **Integration**: GitHub App for automated PR creation

The system crawls `content/en/guides/**/*.md(x)` files, processes them through multiple analyzers, and provides a web interface for reviewing and applying suggested fixes.
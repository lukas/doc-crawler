# DocsQA - W&B Documentation Quality Assurance System

A comprehensive system for automatically detecting and fixing issues in W&B documentation using rule-based analyzers and LLM-powered suggestions.

## Features

- **Multi-analyzer Pipeline**: Links, versions, API/CLI validation, style consistency
- **LLM Integration**: GPT-4 powered clarity, grammar, and accuracy improvements  
- **Smart Verification**: Automated safety checks for suggested patches
- **GitHub Integration**: Automated PR creation with reviewed fixes
- **Embeddings Search**: FAISS-powered document similarity for context
- **Comprehensive API**: Full REST API for issue management and workflow

## Quick Start

### Development Setup

1. **One-time setup**:
```bash
# Run the setup script (installs uv, dependencies, sets up database)
./setup.sh

# Set environment variables (optional)
export OPENAI_API_KEY="your-openai-key"
export GITHUB_APP_ID="your-github-app-id"
```

2. **Start the API server**:
```bash
# Using uv (recommended)
uv run docsqa-server

# Or manually
source .venv/bin/activate && cd docsqa/backend && python app.py
```

3. **Run analysis**:
```bash
# Using uv (recommended)
uv run docsqa-analyze --source manual --no-llm

# Run full analysis (requires OpenAI API key)
uv run docsqa-analyze --source manual

# Debug mode
uv run docsqa-analyze --source manual --debug

# Or manually
source .venv/bin/activate
cd docsqa && PYTHONPATH=backend python -m crawler.run_analysis --source manual
```

4. **View results**:
- API docs: http://localhost:8080/docs
- Health check: http://localhost:8080/health

### Docker Deployment

1. **Set up environment**:
```bash
# Create .env file
cat > .env << EOF
OPENAI_API_KEY=your-openai-key
GITHUB_APP_ID=your-github-app-id
GITHUB_INSTALLATION_ID=your-installation-id
GITHUB_PRIVATE_KEY=your-base64-encoded-private-key
EOF
```

2. **Start services**:
```bash
docker-compose -f docker/docker-compose.yml up -d
```

## Configuration

Main configuration in `configs/config.yml`:

```yaml
repo:
  url: https://github.com/wandb/docs.git
  branch: main

paths:
  include:
    - content/en/guides/**/*.md
    - content/en/guides/**/*.mdx

llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.1

guardrails:
  require_citations: true
  allow_code_edits: false
  max_whitespace_delta_lines: 3
```

## Architecture

### Backend Components

- **Core Services**: Git utils, MDX parsing, document chunking
- **Rule Analyzers**: Link checking, version drift, API/CLI validation, style
- **LLM Engine**: Provider-agnostic client with JSON schema validation
- **Verifier**: Safety checks for automated patches
- **API**: REST endpoints for all operations

### Analysis Pipeline

1. **Repository Sync**: Clone/pull W&B docs, detect changed files
2. **Document Processing**: Parse MDX, extract structure, create chunks
3. **Rule Analysis**: Run fast heuristic checks (links, versions, etc.)
4. **LLM Analysis**: Context-aware clarity/accuracy suggestions
5. **Verification**: Safety checks for auto-apply eligibility
6. **Storage**: Persist issues with provenance and patches

### Issue Lifecycle

```
[Detected] → [Verified] → [Staged] → [PR Created] → [Merged] → [Resolved]
                ↓
           [Auto-apply] ←→ [Manual Review]
```

## API Usage

### List Issues
```bash
curl "http://localhost:8080/api/issues?severity=high&can_auto_apply=true"
```

### Get Issue Details
```bash
curl "http://localhost:8080/api/issues/123"
```

### Create PR
```bash
curl -X POST "http://localhost:8080/api/prs" \
  -H "Content-Type: application/json" \
  -d '{
    "issue_ids": [1, 2, 3],
    "title": "docs: automated fixes",
    "branch_name": "docs/fixes/2025-01-14",
    "commit_strategy": "one-per-file",
    "open_draft": true
  }'
```

### Trigger Analysis
```bash
curl -X POST "http://localhost:8080/api/runs?source=manual"
```

## Rule Catalog

| Rule Code | Description | Severity | Auto-Apply |
|-----------|-------------|----------|------------|
| `LINK_404` | Broken link (404) | High | ❌ |
| `SDKVER_OLD` | Outdated package version | Medium | ✅ |
| `API_DEPRECATED` | Deprecated API usage | High | ✅* |
| `STYLE_TERMINOLOGY` | Non-canonical terms | Low | ✅ |
| `LLM_CLARITY` | Clarity improvement | Medium | ✅* |
| `LLM_ACCURACY` | Accuracy correction | High | ✅* |

*Auto-apply only with proper citations and verification

## CLI Usage

### Run Analysis
```bash
# Full analysis
python -m crawler.run_analysis --source manual

# Rule-based only
python -m crawler.run_analysis --llm=off

# Specific commit
python -m crawler.run_analysis --commit abc123
```

### GitHub PR Creation
```bash
python -m services.github_app --open-pr --issues 1,2,3 --branch docs/fixes/test
```

## Development

### Project Structure
```
docsqa/
├── backend/
│   ├── api/              # FastAPI endpoints
│   ├── core/             # Core services & models
│   ├── crawler/          # Analysis pipeline
│   │   └── analyzers/    # Rule-based analyzers
│   └── services/         # LLM, embeddings, GitHub
├── configs/              # Configuration & catalogs
├── docker/               # Docker setup
└── scripts/              # Development utilities
```

### Adding New Rules

1. Create analyzer in `backend/crawler/analyzers/`
2. Add rule definition to `api/rules.py` 
3. Integrate in `crawler/pipeline.py`
4. Update documentation

### Testing

```bash
# Unit tests
pytest backend/tests/

# Integration test with mini-repo
python scripts/test_e2e.py
```

## Acceptance Tests

The system passes these key acceptance criteria:

- ✅ **Crawl**: Processes all `.md(x)` files under `content/en/guides` 
- ✅ **Link Validation**: Detects broken external links with retries
- ✅ **Version Drift**: Flags outdated `wandb==X.Y.Z` references  
- ✅ **API Deprecation**: Validates API usage against catalogs
- ✅ **LLM Quality**: Provides clarity/accuracy improvements with citations
- ✅ **Safety**: Verifies patches before auto-apply
- ✅ **GitHub PR**: Creates draft PRs with proper formatting
- ✅ **Auto-resolve**: Resolves issues after PR merge

## Monitoring & Observability

- **Structured Logs**: JSON format with component/rule/latency
- **Token Usage**: OpenAI API cost tracking per run
- **Health Checks**: Service availability monitoring  
- **Performance**: Link checker timing, LLM response latency

## Security

- **No Secrets**: Environment variables only, no hardcoded keys
- **Minimal Permissions**: GitHub App scoped to docs repo only
- **Content Filtering**: Redacts sensitive patterns from LLM prompts
- **Verification**: Multi-layer safety checks for automated changes

---

**Built with [Claude Code](https://claude.ai/code)**
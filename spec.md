Overview
Objective: Scan the W&B docs under
https://github.com/wandb/docs/tree/main/content/en/guides, detect issues (typos, grammar, clarity, accuracy, consistency, broken links), propose patches, and let reviewers open a GitHub PR with selected fixes.
Stack (recommended):
Backend: Python 3.11 + FastAPI, async httpx, SQLAlchemy, Alembic
Worker: same env, runs crawler + analyzers
LLM: provider-agnostic via an interface (JSON-mode)
Frontend: React + TypeScript + Vite + Tailwind
DB: Postgres (SQLite in dev)
Search/embeddings: FAISS (local)
Git: system git CLI
Container: Docker + docker-compose
1) Repo Layout (exact)
docsqa/
  backend/
    app.py                # FastAPI app factory
    api/
      issues.py
      files.py
      runs.py
      rules.py
      prs.py
    core/
      config.py
      db.py
      models.py
      schemas.py          # Pydantic response/request objects
      git_utils.py
      linkcheck.py
      mdx_parse.py
      chunker.py
      version_resolver.py
      catalogs.py         # API/CLI catalogs loader
      patches.py          # unified diff helpers
      verifier.py         # guardrails
    crawler/
      run_analysis.py     # entrypoint for one full run
      repo_sync.py        # clone/pull + changed files
      pipeline.py         # orchestrates analyzers per chunk
      analyzers/
        rule_spell.py     # optional; used to seed LLM
        rule_style.py
        rule_links.py
        rule_versions.py
        rule_api_cli.py
        rule_structure.py
        llm_quality.py    # LLM clarity/accuracy/grammar
    services/
      llm_client.py       # provider adapter with JSON schema validation
      embeddings.py       # FAISS index builder/query
      github_app.py       # PR creation, auth
    migrations/           # Alembic
  frontend/
    src/
      main.tsx
      App.tsx
      components/
        IssueList.tsx
        IssueDetail.tsx
        FileTree.tsx
        RunDashboard.tsx
        RuleSettings.tsx
        PrCart.tsx
      lib/api.ts
      lib/format.ts
  configs/
    config.yml
    dictionaries/wandb_terms.txt
    catalogs/wandb_api.json
    catalogs/wandb_cli.json
  docker/
    Dockerfile.backend
    Dockerfile.frontend
    docker-compose.yml
  scripts/
    dev_seed.sh           # seed DB with example data
    run_once.sh           # run a single analysis locally
  README.md
2) Configuration (exact file)
configs/config.yml
repo:
  url: https://github.com/wandb/docs.git
  branch: main
paths:
  include:
    - content/en/guides/**/*.md
    - content/en/guides/**/*.mdx
  exclude: []
crawler:
  poll_minutes: 60
links:
  timeout_ms: 4000
  concurrency: 8
  per_host_limit: 2
versions:
  package: wandb
  allow_majors_behind: 0
  allow_minors_behind: 1
style:
  require_one_h1: true
  require_img_alt: true
terminology:
  canonical:
    - "Weights & Biases|W&B"
    - "Artifacts"
llm:
  provider: openai     # "openai" | "azure" | "local"
  model: gpt-4o-mini
  temperature: 0.1
  max_output_tokens: 1200
  json_mode: true
  rate_limits:
    rpm: 200
    tpm: 800000
  budgets:
    tokens_per_run: 2000000
retrieval:
  embedding_model: text-embedding-3-small
  index_path: .cache/faiss
  k_neighbors: 5
guardrails:
  require_citations: true
  allow_code_edits: false
  max_whitespace_delta_lines: 3
pr:
  default_branch_prefix: docs/fixes
  draft: true
  reviewers: ["docs-maintainers"]
server:
  host: 0.0.0.0
  port: 8080
db:
  url: postgresql+psycopg://user:pass@db:5432/docsqa
Environment variables (12-factor):
GITHUB_APP_ID, GITHUB_INSTALLATION_ID, GITHUB_PRIVATE_KEY (PEM, base64)
OPENAI_API_KEY (or provider equivalent)
DATABASE_URL (overrides db.url)
3) Database Schema (SQLAlchemy/Alembic fields)
files
id PK
path TEXT unique
sha TEXT (blob SHA)
title TEXT
lang TEXT default en
last_seen_commit TEXT
status TEXT enum(active,deleted)
timestamps
analysis_runs
id PK
commit_sha TEXT
started_at, finished_at TIMESTAMP
source TEXT enum(manual,scheduled,webhook)
status TEXT enum(running,success,failed)
stats JSONB
llm_token_in BIGINT default 0
llm_token_out BIGINT default 0
llm_cost_estimate NUMERIC default 0
issues
id PK
file_id FK->files
rule_code TEXT
severity TEXT enum(low,medium,high,critical)
title TEXT
description TEXT
snippet TEXT
line_start INT NULL
line_end INT NULL
col_start INT NULL
col_end INT NULL
evidence JSONB
proposed_snippet TEXT NULL
suggested_patch TEXT NULL # unified diff
citations JSONB NULL
confidence FLOAT NULL
provenance JSONB NOT NULL # ["rule"] | ["llm"] | ["rule","llm"]
can_auto_apply BOOL NOT NULL default false
state TEXT enum(open,acknowledged,ignored,resolved) default open
first_seen_run_id FK->analysis_runs
last_seen_run_id FK->analysis_runs
pr_state TEXT enum(none,staged,committed,pr_opened,pr_merged,pr_closed) default none
pr_url TEXT NULL
timestamps
rules
rule_code PK
name TEXT
category TEXT
default_severity TEXT
config JSONB
enabled BOOL
Uniqueness guard: composite unique index on (file_id,rule_code,line_start,title).
4) Crawler & Pipeline (step-by-step)
4.1 Repo sync
If no local clone, git clone {repo.url} to /data/repo.
git fetch origin {branch}; git checkout {branch}; git reset --hard origin/{branch}.
Record HEAD commit SHA for the run.
If previous run exists:
Get changed files: git diff --name-status {last_commit}..HEAD.
Filter by include patterns, exclude by config.
For each included file, read bytes + blob SHA; if unchanged (same SHA) → skip.
4.2 Parsing & chunking
Parse frontmatter (YAML) if present.
Use a Markdown/MDX parser; create an AST.
Extract:
headings (with line numbers)
paragraphs, lists
links/images (URL + text + lines)
code fences & inline code (language, content, lines)
Chunk by H2/H3 boundaries into ~2–3k token targets; record chunk_id, start_line, end_line.
Build rendered text for each chunk (exclude fenced code from text body but keep placeholders & references).
4.3 Rule-based analyzers (fast heuristics)
rule_links.py: validate internal & external links (HEAD/GET with retry).
rule_versions.py: resolve latest wandb from PyPI JSON; detect version drift via regex.
rule_api_cli.py: scan code blocks for wandb. symbols and wandb <cli> patterns; compare to catalogs.
rule_style.py: terminology & headings & image alt text.
(Optional) rule_spell.py: basic spell prefilter to reduce LLM load by passing likely trouble sentences/snippets.
Each rule generates issues with provenance=["rule"]. Do not create patches yet.
4.4 Retrieval index
Compute embeddings for each chunk (skip unchanged chunks—key on file SHA + [start_line,end_line]).
Build/refresh FAISS index; store vectors on disk.
4.5 LLM Quality Engine (clarity/accuracy/grammar)
For each chunk:
Build a context pack:
Current chunk text + +/- 150 lines around boundaries.
Top-k similar chunks via FAISS (k from config).
Catalog entries relevant to any wandb. symbol or CLI seen.
Latest wandb version, and any link resolution outcomes.
Canonical terminology list.
Call LLM with strict JSON schema (below).
Validate JSON; if invalid → one retry with stricter guidance.
For each suggestion:
Build minimal unified diff (suggested_patch) from original_snippet → proposed_snippet.
Run verifier (see §6) to set can_auto_apply.
Persist these as issues with provenance=["llm"] or merged into existing rule issues (if same lines/rule—keep higher severity, merge citations).
5) LLM Prompt & JSON (copy-pasteable)
System:
You are a careful technical editor for the Weights & Biases (W&B) Guides.
Propose MINIMAL, SAFE edits in Markdown source:
- Fix spelling/grammar (code-aware; do not change code).
- Improve clarity without changing meaning.
- Flag accuracy issues ONLY if grounded by provided citations (repo text, catalogs, or explicit facts).
- Respect code fences/inline code; suggest code fixes only when supported by catalogs.
Output VALID JSON conforming to the response schema. Include citations for accuracy claims.
User (templated):
CURRENT FILE: {file_path}
LINES: {start_line}-{end_line}

CHUNK:
<<<
{chunk_text}
>>>

SURROUNDING CONTEXT (read-only):
<<<
{context_text}
>>>

RETRIEVED SNIPPETS (read-only):
{[ {path, lines, text}, ... ]}

FACTS:
- latest_wandb_version = {X.Y.Z}
- api_catalog_keys = {["wandb.init", "wandb.log", ...]}
- cli_catalog_keys = {["wandb login", "wandb launch", ...]}
- canonical_terms = {["Weights & Biases|W&B", "Artifacts"]}

RULES:
- NEVER fabricate facts; if uncertain, emit a "question" suggestion.
- DO NOT change code unless catalogs justify it.
- Keep markdown structure intact.

Return JSON only.
Response JSON Schema (enforce in code):
{
  "type": "object",
  "properties": {
    "suggestions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type","rule_code","severity","confidence","title","description","file_path","line_start","line_end","original_snippet","proposed_snippet","citations","tags"],
        "properties": {
          "type": { "enum": ["text_edit","code_edit","delete","insert","question"] },
          "rule_code": { "enum": ["LLM_SPELL","LLM_GRAMMAR","LLM_CLARITY","LLM_ACCURACY","LLM_CONSISTENCY","LLM_UNSURE"] },
          "severity": { "enum": ["low","medium","high","critical"] },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "file_path": { "type": "string" },
          "line_start": { "type": "integer" },
          "line_end": { "type": "integer" },
          "original_snippet": { "type": "string" },
          "proposed_snippet": { "type": "string" },
          "citations": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["type"],
              "properties": {
                "type": { "enum": ["file","catalog","fact"] },
                "path": { "type": "string" },
                "line_start": { "type": "integer" },
                "line_end": { "type": "integer" },
                "source": { "type": "string" },
                "key": { "type": "string" },
                "value": { "type": "string" }
              }
            }
          },
          "tags": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "notes": { "type": "string" }
  },
  "required": ["suggestions"]
}
6) Verifier (guardrails)
Run before setting can_auto_apply=true:
Diff scope check: Only lines [line_start,line_end] change; no other parts touched.
Markdown node check: Re-parse original and proposed snippets; only paragraph/text nodes changed unless type=="code_edit".
Whitespace churn: Reject if > max_whitespace_delta_lines changed with no semantic change.
Catalog guard:
If type=="code_edit": require a catalog citation; else mark can_auto_apply=false.
Link check: Any added/changed URLs must pass linkcheck (2 retries).
Version check: If version literals are changed, confirm against latest_wandb_version.
If any guard fails → can_auto_apply=false and append a note to description (“manual review required”).
7) GitHub PR Flow
Pre-req: Install a GitHub App with scopes: contents:write, pull_requests:write. Store credentials in env.
Endpoints (backend):
POST /api/prs
{
  "issue_ids": [1,2,3],
  "title": "docs: automated fixes (run 42)",
  "branch_name": "docs/fixes/2025-08-14/42",
  "commit_strategy": "one-per-file",   // "squash" | "one-per-file" | "one-per-issue"
  "open_draft": true
}
Behavior:
Create branch off latest origin/main.
For each issue: if can_auto_apply==true, apply suggested_patch. If false → include a comment block with suggested snippet in the commit (or skip and collect into PR body “comments”).
Commit according to commit_strategy.
Push branch; open PR with:
Labels: automated, unique rules present.
Reviewers from config.
Body includes: counts by rule/severity, per-file collapsible diffs, citations text, run metadata.
Update issues.pr_state and issues.pr_url.
POST /api/issues/{id}/stage — apply patch to working tree (no commit), cache staged set.
POST /api/issues/{id}/apply — same but immediate apply to current branch (admin only).
PR Body Template (markdown):
## Docs QA Automated Fixes (Run {run_id} @ {commit_sha})

**Summary**
- {N} clarity edits
- {M} spelling/grammar
- {K} accuracy/consistency (catalog-backed)

**Checklists**
- [ ] I reviewed clarity edits (no semantic change)
- [ ] Accuracy changes cite catalogs or adjacent docs
- [ ] Link checks passed

<details><summary>Per-file changes</summary>

### {path}
Rules: {STYLE_TERM, LLM_CLARITY, ...}
Citations: 
- {type}:{path or key} lines {a}-{b}
- ...

```diff
{truncated unified diff}
</details> ```
8) Backend API (exact)
GET /api/issues?state=&severity=&rule=&file=&q=&provenance=&has_patch=&can_auto_apply=&page=&sort=
GET /api/issues/{id}
PATCH /api/issues/{id} body: { "state": "acknowledged|ignored|resolved" }
POST /api/issues/bulk body: { "filter": {...}, "state": "..." }
GET /api/files?path_prefix=&q=
GET /api/files/{id} → { content, headings, issue_counts }
GET /api/runs/latest / GET /api/runs/{id}
POST /api/runs → trigger run now
GET /api/rules
PATCH /api/rules/{rule_code} → toggle/adjust severity/config
POST /api/prs (above)
Responses use Pydantic schemas; include pagination keys.
9) Frontend (exact screens & UX)
9.1 Issues List
Filters: severity, rule, state, provenance (Rule/LLM), file prefix, Only new since last run.
Columns: Rule, Severity, File:Line, Title, Confidence (if LLM), Auto-apply badge.
Bulk select → Add to PR cart / Change state.
9.2 Issue Detail
Left: rendered Markdown with inline highlight (line numbers).
Right: metadata:
Rule, severity, confidence, provenance
Citations (expandable list)
Verifier status badge (passed/failed)
Diff viewer (original vs proposed snippet).
Buttons: Add to PR cart, Acknowledge, Ignore, Mark Resolved.
9.3 PR Cart & Modal
Shows selected issues grouped by file.
Warnings for non-auto-apply patches.
Options: branch name (prepopulated), commit strategy, draft toggle, reviewers (from config).
Create PR → success toast + link.
9.4 Runs Dashboard
Last run status, counts by rule/severity, sparkline of open issues.
LLM token in/out and cost estimate.
9.5 Rules Settings
Toggle rule on/off, change default severity, edit canonical terms, upload dictionary additions.
10) Acceptance Tests (copy to QA checklist)
Crawl: A run processes all .md(x) under content/en/guides at main@HEAD; unchanged files are skipped on subsequent runs.
Link checks: One known broken external link is flagged (LINK404), and one working link is not flagged.
Version drift: A page containing pip install wandb==OLDVER yields SDKVER_OLD (high) with the latest version listed in evidence.
API deprecation: A snippet using a deprecated wandb API is flagged with catalog citation.
LLM clarity: A wordy sentence produces a minimal rewrite (LLM_CLARITY) with can_auto_apply=true.
LLM accuracy: A wrong default (“defaults to 64”) is flagged (LLM_ACCURACY) with file/catalog citation; can_auto_apply=true if the rewrite simply corrects the number.
Guardrail: An LLM suggestion that alters code without a catalog citation is not auto-applied (can_auto_apply=false).
UI: Filters work; Issue Detail shows diff + citations; keyboard nav j/k moves selection.
PR: Selecting three auto-apply issues creates a draft PR with correct branch name, labels, body sections, diffs, and reviewers; issues record pr_url and pr_opened.
Auto-resolve: After PR merge and rerun, those issues move to resolved.
11) Developer Steps (how to build, in order)
Scaffold backend: FastAPI app, /healthz.
DB & models: tables + Alembic migration 0001.
Repo sync: repo_sync.py with clone/pull and changed file list.
MDX parse + chunker: return chunks with line ranges.
Link checker (async httpx) with concurrency + retries + cache.
Version resolver (PyPI JSON) + rule_versions analyzer.
Catalogs loader + api/cli analyzer.
Spell/style/structure analyzers (lightweight).
Embeddings + FAISS service.
LLM client with JSON schema validation and prompts from §5.
llm_quality analyzer + verifier from §6 + patches helper for unified diffs.
API endpoints for issues/files/runs/rules.
Frontend: Issue list → Issue detail → PR cart → PR creation.
GitHub App integration, PR service, PR body template.
Docker compose: backend, db, frontend, nginx (optional).
CI: run black, ruff, pytest, and a tiny e2e against a seeded mini-repo.
12) Error Handling & Observability
Structured logs (JSON): component, file, rule_code, latency, tokens_in/out.
Metrics:
Run duration
Issues per rule/severity
Link checker failures/timeouts
LLM invalid-JSON rate, refusal rate
PR success rate
Backoff & retry on network/LLM errors; abort run if >30% link checks fail (likely outage).
Store last successful run id in DB; a partial run is marked failed.
13) Security/Privacy
Do not send entire files unnecessarily; only chunk + minimal retrieval snippets in LLM prompt.
Redact tokens/keys (regex) in prompts.
The GitHub App is restricted to the docs repo.
Admin endpoints token-protected; read endpoints rate-limited.
14) Command-Line Entrypoints
python -m crawler.run_analysis --config configs/config.yml --source webhook
python -m crawler.run_analysis --llm=off (debug)
python -m services.github_app --open-pr --issues 1,2,3 --branch docs/fixes/test
15) Definition of Done
All acceptance tests in §10 pass.
A draft PR can be created from the UI with at least one auto-apply LLM clarity fix and one accuracy fix, both verified.
After merging the PR and rerunning, the corresponding issues are auto-resolved.
The team can toggle rules and update the custom dictionary and catalogs via the UI.
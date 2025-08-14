import os
import yaml
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from pathlib import Path


class RepoConfig(BaseModel):
    url: str
    branch: str = "main"


class PathsConfig(BaseModel):
    include: List[str] = []
    exclude: List[str] = []


class CrawlerConfig(BaseModel):
    poll_minutes: int = 60


class LinksConfig(BaseModel):
    timeout_ms: int = 4000
    concurrency: int = 8
    per_host_limit: int = 2


class VersionsConfig(BaseModel):
    package: str = "wandb"
    allow_majors_behind: int = 0
    allow_minors_behind: int = 1


class StyleConfig(BaseModel):
    require_one_h1: bool = True
    require_img_alt: bool = True


class TerminologyConfig(BaseModel):
    canonical: List[str] = []


class LLMRateLimits(BaseModel):
    rpm: int = 200
    tpm: int = 800000


class LLMBudgets(BaseModel):
    tokens_per_run: int = 2000000


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_output_tokens: int = 1200
    json_mode: bool = True
    rate_limits: LLMRateLimits = Field(default_factory=LLMRateLimits)
    budgets: LLMBudgets = Field(default_factory=LLMBudgets)


class RetrievalConfig(BaseModel):
    embedding_model: str = "text-embedding-3-small"
    index_path: str = ".cache/faiss"
    k_neighbors: int = 5


class GuardrailsConfig(BaseModel):
    require_citations: bool = True
    allow_code_edits: bool = False
    max_whitespace_delta_lines: int = 3


class PRConfig(BaseModel):
    default_branch_prefix: str = "docs/fixes"
    draft: bool = True
    reviewers: List[str] = ["docs-maintainers"]


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class DBConfig(BaseModel):
    url: str = "postgresql+psycopg://user:pass@db:5432/docsqa"


class Config(BaseModel):
    repo: RepoConfig
    paths: PathsConfig = Field(default_factory=PathsConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    links: LinksConfig = Field(default_factory=LinksConfig)
    versions: VersionsConfig = Field(default_factory=VersionsConfig)
    style: StyleConfig = Field(default_factory=StyleConfig)
    terminology: TerminologyConfig = Field(default_factory=TerminologyConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    pr: PRConfig = Field(default_factory=PRConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    db: DBConfig = Field(default_factory=DBConfig)


class Settings:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.getenv("CONFIG_PATH", "configs/config.yml")
        self._config: Optional[Config] = None
        self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML file and environment variables"""
        config_file = Path(self.config_path)
        
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # Override with environment variables
        if os.getenv("DATABASE_URL"):
            if "db" not in config_data:
                config_data["db"] = {}
            config_data["db"]["url"] = os.getenv("DATABASE_URL")
        
        # Override other important env vars
        if os.getenv("GITHUB_APP_ID"):
            if "github" not in config_data:
                config_data["github"] = {}
            config_data["github"]["app_id"] = os.getenv("GITHUB_APP_ID")
        
        if os.getenv("OPENAI_API_KEY"):
            if "llm" not in config_data:
                config_data["llm"] = {}
            config_data["llm"]["api_key"] = os.getenv("OPENAI_API_KEY")
        
        self._config = Config(**config_data)
    
    @property
    def config(self) -> Config:
        if self._config is None:
            self._load_config()
        return self._config
    
    def reload(self):
        """Reload configuration from file"""
        self._config = None
        self._load_config()


# Global settings instance
settings = Settings()


# Environment variable getters for sensitive data
def get_github_app_id() -> str:
    return os.getenv("GITHUB_APP_ID", "")


def get_github_installation_id() -> str:
    return os.getenv("GITHUB_INSTALLATION_ID", "")


def get_github_private_key() -> str:
    return os.getenv("GITHUB_PRIVATE_KEY", "")


def get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def get_database_url() -> str:
    return os.getenv("DATABASE_URL") or settings.config.db.url
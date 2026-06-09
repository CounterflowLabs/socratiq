from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://socratiq:socratiq@localhost:5432/socratiq"
    redis_url: str = "redis://localhost:6379/0"

    # Security
    llm_encryption_key: str = ""

    # Bilibili (optional — for authenticated subtitle access)
    bilibili_sessdata: str = ""
    bilibili_bili_jct: str = ""
    bilibili_buvid3: str = ""

    # File uploads
    upload_dir: str = "uploads"

    # Whisper ASR (fallback when no subtitles available)
    whisper_mode: str = "local"      # "api" = OpenAI Whisper API, "local" = local whisper model
    whisper_model: str = "base"      # local model size: tiny/base/small/medium/large
    whisper_api_key: str = ""
    whisper_api_base_url: str = "https://api.groq.com/openai/v1"
    whisper_api_model: str = "whisper-large-v3"

    # Auth
    jwt_secret_key: str = "change-me-in-production"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    google_client_id: str = ""

    # Observability
    sentry_dsn: str = ""

    # Agentic course-generation pipeline (Phase 3). When True, course
    # generation re-plans the section structure with the critic-gated
    # video→course outline graph (consolidates fragmented chunks into a
    # coherent, difficulty-ramped outline before assembly) and runs the
    # advisory course critic. When False it uses the ingestion-time
    # SectionPlanner buckets directly (today's deterministic behavior).
    # Override per-deployment via the AGENTIC_VIDEO_PIPELINE env var.
    agentic_video_pipeline: bool = True

    # Live reference fetching (arXiv today) at ingestion: turns a source's
    # concepts into real, citable references cached on the source, so lessons'
    # further_reading cites fetched papers (real URLs) instead of model memory.
    # Degrades gracefully to curated + model-knowledge when off or on failure.
    # The pipeline is complete: fetch -> ReferenceRanker (LLM precision pass,
    # drops off-topic) -> cache -> consume -> verified-url enforcement -> render.
    # DEFAULT OFF, though, because arXiv is a weak RECALL source: its relevance
    # search doesn't surface seminal papers for most queries (and rate-limits),
    # so even perfect ranking yields little — not worth the per-ingestion fetch+
    # rank cost. Add a citation-aware source (Semantic Scholar) to the pluggable
    # fetcher to fix recall, then flip this on. Until then further_reading uses
    # the curated set + the model's own well-known classics (urls enforced).
    reference_search_enabled: bool = False

    # Semantic Scholar API key (optional). Keyless access is heavily rate-limited
    # (429s), so a free key (https://www.semanticscholar.org/product/api) is
    # required for the citation-ranked recall source to actually return results.
    # When set, build_reference_fetcher adds SemanticScholarReferenceFetcher
    # (surfaces seminal works by citation count) ahead of arXiv. Inject via the
    # SEMANTIC_SCHOLAR_API_KEY env var.
    semantic_scholar_api_key: str = ""

    # LLM timeouts and concurrency (Tier 3/4 of async refactor)
    # Note: idle timeout doubles as the per-request read deadline for
    # non-streaming OpenAI-compatible providers, so set generously enough
    # for slow local backends (Ollama on CPU can hit 2-3 minutes per call).
    llm_total_timeout: float = 600.0  # non-stream wall-clock cap
    llm_idle_timeout: float = 300.0   # streaming inter-chunk idle cap (and non-stream read)
    llm_max_concurrency: int = 4      # gather() semaphore for page-level gen

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()

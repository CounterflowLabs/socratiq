from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.database import engine
from app.api.routes import activation, auth, health, models, model_routes, tasks, sources, courses, chat, diagnostic, exercises, reviews, knowledge_graph, translations, labs, setup
from app.api.routes.progress import router as progress_router
from app.api.middleware.correlation import CorrelationIdMiddleware


_DEFAULT_SECRETS = {"change-me-in-production", "change-me-too", ""}


def _resolve_cors_origins(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts:
        return parts
    # Dev fallback — common local hosts. Production sets cors_origins explicitly.
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


def _check_production_secrets(settings) -> None:
    """Fail fast if production is running with placeholder secrets."""
    if settings.env != "production":
        return
    bad: list[str] = []
    if settings.jwt_secret_key in _DEFAULT_SECRETS:
        bad.append("JWT_SECRET_KEY")
    if settings.llm_encryption_key in _DEFAULT_SECRETS:
        bad.append("LLM_ENCRYPTION_KEY")
    if bad:
        raise RuntimeError(
            f"Refusing to start in production: insecure default(s) for {', '.join(bad)}. "
            "Override via environment variables."
        )


def _maybe_init_sentry(settings) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


settings = get_settings()
_check_production_secrets(settings)
_maybe_init_sentry(settings)

app = FastAPI(title="Socratiq", version="0.1.0", lifespan=lifespan)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router)
app.include_router(activation.router)
app.include_router(models.router)
app.include_router(model_routes.router)
app.include_router(tasks.router)
app.include_router(sources.router)
app.include_router(courses.router)
app.include_router(chat.router)
app.include_router(diagnostic.router)
app.include_router(exercises.router)
app.include_router(reviews.router)
app.include_router(knowledge_graph.router)
app.include_router(translations.router)
app.include_router(labs.router)
app.include_router(setup.router)
app.include_router(progress_router)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Install OpenTelemetry first — AgentRuntime / MentorAgent snapshot the
# default tracer at __init__, so the swap must happen before any service
# class is constructed. Importing app modules below transitively imports
# those classes, but no instances are created until route handlers run.
from app.services.observability.bootstrap import init_otel, instrument_fastapi

init_otel(service_name="socratiq-backend")

from app.db.database import engine
from app.api.routes import health, models, model_routes, tasks, sources, courses, chat, diagnostic, exercises, reviews, knowledge_graph, translations, labs, setup
from app.api.routes.progress import router as progress_router
from app.api.middleware.correlation import CorrelationIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="Socratiq", version="0.1.0", lifespan=lifespan)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
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

# FastAPI auto-instrumentation reads app.routes to build URL templates, so it
# has to run AFTER include_router. No-op when OTel isn't installed.
instrument_fastapi(app)

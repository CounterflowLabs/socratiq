from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import engine
from app.api.routes import auth, health, models, model_routes, tasks, sources, courses, chat, diagnostic, exercises, reviews, knowledge_graph
from app.api.middleware.correlation import CorrelationIdMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="LearnMentor", version="0.1.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
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


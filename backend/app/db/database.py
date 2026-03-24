from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

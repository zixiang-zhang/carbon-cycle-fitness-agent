"""CarbonCycle-FitAgent 后端服务入口。"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.core.database import close_db, init_db
from app.core.logging import get_logger, setup_logging
from app.core.scheduler import start_scheduler, stop_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    管理整个 FastAPI 服务的生命周期。

    启动阶段负责初始化日志、数据库和定时任务；
    关闭阶段负责按相反顺序释放资源，避免数据库连接或后台任务遗留。
    """
    setup_logging()
    logger.info("Starting CarbonCycle-FitAgent...")

    await init_db()
    start_scheduler()

    logger.info("Application started successfully")
    yield

    logger.info("Shutting down...")
    stop_scheduler()
    await close_db()
    logger.info("Application stopped")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用对象。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI agent for carbon-cycle diet and fitness planning.",
        lifespan=lifespan,
    )

    # 前端页面和本地调试工具都会直接访问这个 API，
    # 因此这里统一放开 CORS，避免本地联调时被浏览器拦截。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 所有业务路由统一挂在 `/api` 前缀下，便于前后端约定接口路径。
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )

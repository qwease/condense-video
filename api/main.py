"""
FastAPI 应用主入口

视频内容提炼服务 - Python 后端
结合语音转录和 PPT OCR 分析，从长视频中提取核心知识。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.logging import setup_logging
from api.routers import health_router, tasks_router, videos_router, ws_router

# 设置日志
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理

    启动时: 初始化 Redis 连接，检查健康状态
    关闭时: 清理资源
    """
    # 启动
    logger.info("Starting Condense Video API...")
    logger.info(f"Storage backend: {settings.storage_backend}")
    logger.info(f"DashScope API: {'*' * 20}{settings.dashscope_api_key[-8:]}")

    # 初始化 Redis 连接
    try:
        from services.redis_client import get_redis

        redis = get_redis()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

    # 初始化存储
    try:
        from core.storage import get_storage

        storage = get_storage()
        logger.info(f"Storage backend initialized: {settings.storage_backend}")
    except Exception as e:
        logger.warning(f"Storage initialization warning: {e}")

    yield

    # 关闭
    logger.info("Shutting down Condense Video API...")

    # 关闭 Redis 连接
    try:
        from services.redis_client import close_redis

        close_redis()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")


# 创建 FastAPI 应用
app = FastAPI(
    title="Condense Video API",
    description="视频内容提炼服务 - 结合语音转录和 PPT OCR 分析，从长视频中提取核心知识",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ==================== CORS 配置 ====================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # 开发前端
        "http://localhost:5173",  # Vite 开发服务器
        "http://localhost:8080",  # 其他前端框架
        # 添加生产环境域名
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 路由注册 ====================

# 系统健康检查
app.include_router(health_router)

# 任务管理
app.include_router(tasks_router)

# 视频处理
app.include_router(videos_router)

# WebSocket 进度推送
app.include_router(ws_router)


# ==================== 根路径 ====================


@app.get("/")
async def root() -> dict[str, str]:
    """根路径 - API 信息"""
    return {
        "name": "Condense Video API",
        "version": "1.0.0",
        "description": "视频内容提炼服务 - 结合语音转录和 PPT OCR 分析，从长视频中提取核心知识",
        "docs": "/docs",
        "health": "/health",
    }


# ==================== 全局异常处理 ====================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc) -> JSONResponse:
    """全局异常处理器"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred",
                "details": {"error": str(exc)} if settings.api_debug else {},
            }
        },
    )


# ==================== 开发模式配置 ====================

if settings.api_debug:
    # 开启详细日志
    import logging

    logging.getLogger("uvicorn").setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    logger.warning("Debug mode enabled - sensitive information may be logged")


# ==================== 运行入口 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        workers=settings.api_workers if not settings.api_reload else 1,
        log_level="info",
    )

"""
API 路由模块

导出所有路由模块
"""

from .health import router as health_router
from .tasks import router as tasks_router
from .videos import router as videos_router
from .ws import router as ws_router

__all__ = [
    "health_router",
    "tasks_router",
    "videos_router",
    "ws_router",
]

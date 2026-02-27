"""
日志配置模块

使用 loguru 配置结构化日志。
"""

import sys
from loguru import logger
from pathlib import Path
from typing import Any


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> Any:
    """
    配置日志系统

    配置多个日志处理器：
    - 控制台输出（彩色格式）
    - 所有日志文件（app.log）
    - 错误日志文件（error.log）

    Args:
        log_level: 控制台日志级别，默认 INFO
        log_dir: 日志文件目录，默认 logs

    Returns:
        配置后的 logger 实例
    """
    # 移除默认处理器
    logger.remove()

    # 控制台输出（彩色格式）
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        level=log_level,
        colorize=True,
    )

    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # 所有日志文件
    logger.add(
        log_path / "app.log",
        rotation="100 MB",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        enqueue=True,  # 异步写入，避免阻塞
    )

    # 错误日志文件
    logger.add(
        log_path / "error.log",
        rotation="50 MB",
        retention="90 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR",
        enqueue=True,
    )

    logger.info(f"Logging configured: level={log_level}, dir={log_dir}")

    return logger


def get_logger(name: str | None = None) -> Any:
    """
    获取带有上下文的 logger

    Args:
        name: 可选的模块名称，用于日志上下文

    Returns:
        logger 实例
    """
    if name:
        return logger.bind(module=name)
    return logger


# 任务日志辅助函数
def log_task_event(task_id: str, event: str, message: str = "", **kwargs: Any) -> None:
    """
    记录任务相关事件

    Args:
        task_id: 任务 ID
        event: 事件类型 (STARTED, SUCCESS, FAILURE, RETRY, etc.)
        message: 可选的附加消息
        **kwargs: 额外的上下文信息
    """
    log_fn = logger.info

    if event == "STARTED":
        log_fn = logger.info
    elif event == "SUCCESS":
        log_fn = logger.info
    elif event == "FAILURE":
        log_fn = logger.error
    elif event == "RETRY":
        log_fn = logger.warning

    context = {"task_id": task_id, "event": event, **kwargs}
    if message:
        log_fn(f"Task {task_id}: {message}", **context)
    else:
        log_fn(f"Task {task_id}: {event}", **context)


# 初始化日志（在导入时自动执行）
# 在生产环境中，应在应用启动时显式调用 setup_logging

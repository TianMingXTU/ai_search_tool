"""logging_config module.

FILENAME    : logging_config.py
Date        : 2026/08/14 11:17:34
Author      : Huijian Qin
Version     : 1.0.0
Description : 基于 loguru 的全局日志配置模块

Attributes:


Example:
    >>> from logging_config import setup_logger
    >>>

"""

import sys
from pathlib import Path
from loguru import logger

# 日志输出目录
LOG_DIR = Path(__file__).resolve().parent / "logs"


def setup_logger(log_level: str = "INFO") -> None:
    """初始化 loguru 日志配置"""
    logger.remove()

    # 1. 控制台输出
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        enqueue=True,  # 支持 asyncio 异步安全写入
    )

    # 2. 文件输出（按 10 MB 切分，保留 7 天，自动创建 logs 文件夹）
    logger.add(
        LOG_DIR / "app.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
        rotation="10 MB",  # 日志文件超过 10MB 自动切分
        retention="7 days",  # 日志保留 7 天
        encoding="utf-8",
        enqueue=True,
    )


__all__ = ["logger", "setup_logger"]


if __name__ == "__main__":
    setup_logger("DEBUG")
    logger.info("日志系统初始化成功！")
    logger.debug("这是一个调试日志")

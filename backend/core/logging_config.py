"""
日志配置
========
统一 structlog 渲染格式。在 main.py 启动时调用 setup_logging()。
"""
import sys
import structlog


def setup_logging(log_level: str = "INFO"):
    """
    配置 structlog：统一时间戳 + 日志级别 + 事件名 + 结构化参数。

    输出示例:
      2026-04-04 09:30:00 [INFO] cache_cleanup_done removed=5 max_age_days=7
      2026-04-04 09:30:01 [WARNING] source_init_timeout source=tushare timeout=8
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),
                pad_event=30,
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), "getLevelName")(log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

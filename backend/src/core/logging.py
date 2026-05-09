"""结构化 JSON 日志配置，适配 ELK 日志收集"""

import json
import logging
import sys
from datetime import datetime, timezone

from core.config import settings


class JSONFormatter(logging.Formatter):
    """将日志格式化为 JSON，方便 Elasticsearch 索引"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "extra") and record.extra:
            log_entry["extra"] = record.extra

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """配置应用日志"""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # 清除已有 handler，避免重复
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # 降低第三方库的日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pymilvus").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)

    root_logger.info(
        "日志系统初始化完成",
        extra={"extra": {"log_level": settings.LOG_LEVEL, "app": settings.APP_NAME}},
    )

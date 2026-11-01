import logging
import sys
from typing import Any


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "task_id"):
            log_data["task_id"] = record.task_id
        if hasattr(record, "execution_id"):
            log_data["execution_id"] = record.execution_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return (
            f"[{log_data['timestamp']}] [{log_data['level']}] [{log_data['logger']}] "
            f"{log_data['message']}"
        )


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = StructuredFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Clear existing handlers
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Silence overly verbose loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from app.core.config import settings


def setup_logger(name: str = "permission_audit") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    info_file = os.path.join(settings.LOG_DIR, f"{name}_info.log")
    info_handler = TimedRotatingFileHandler(
        info_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    logger.addHandler(info_handler)

    error_file = os.path.join(settings.LOG_DIR, f"{name}_error.log")
    error_handler = TimedRotatingFileHandler(
        error_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger


logger = setup_logger()

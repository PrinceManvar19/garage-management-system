import logging
import os
import shutil
from pathlib import Path


LOGGER_NAME = "garage_app"


def configure_app_logging(app_root):
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_path = Path(app_root) / "logs.txt"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_info(message):
    logging.getLogger(LOGGER_NAME).info(message)


def log_error(message):
    logging.getLogger(LOGGER_NAME).error(message)


def backup_database(db_path):
    source = Path(db_path)
    if not source.exists():
        return

    backup_dir = source.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "garage_backup.db"
    shutil.copy2(source, backup_path)

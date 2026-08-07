import logging
import os
import sys
from pathlib import Path


def setup_logging(name: str) -> logging.Logger:
    """Console + file logging. File goes to $LOGS_DIR/<name>.log (default ./logs)."""
    logs_dir = Path(os.environ.get("LOGS_DIR", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(logs_dir / f"{name}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    return logging.getLogger(name)

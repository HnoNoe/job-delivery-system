"""集中日志配置。"""
import logging
from pathlib import Path

import config

def get_logger(name="jobdelivery"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        fh = logging.FileHandler(config.LOG_DIR / "system.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger

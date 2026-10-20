"""集中日志配置。"""
import logging
from pathlib import Path

import config

_logger = None


def get_logger(name="jobdelivery"):
    global _logger
    if _logger is None:
        log_dir = Path(config.BASE_DIR) / "logs"
        log_dir.mkdir(exist_ok=True)
        _logger = logging.getLogger(name)
        if not _logger.handlers:
            _logger.setLevel(logging.INFO)
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            fh = logging.FileHandler(log_dir / "system.log", encoding="utf-8")
            fh.setFormatter(fmt)
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            _logger.addHandler(fh)
            _logger.addHandler(sh)
    return _logger

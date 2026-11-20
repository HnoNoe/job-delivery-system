"""Isolate command-line regression scripts from real databases and sessions."""
import atexit
import logging
import os
from pathlib import Path
import tempfile

_temp = None


def isolate_test_environment():
    global _temp
    if _temp is not None:
        return
    _temp = tempfile.TemporaryDirectory(prefix="jobdelivery-test-")
    os.environ["JOBDELIVERY_HOME"] = _temp.name
    os.environ["JOBDELIVERY_DB"] = str(Path(_temp.name) / "data" / "test.db")
    # 测试强制走本机 SQLite，绝不触碰云端统一字段数据库
    os.environ["JOBDELIVERY_DB_URL"] = "sqlite"
    # 测试不访问真实平台：登录态检测只做本地判断
    os.environ["JOBDELIVERY_LOGIN_CHECK"] = "0"
    def cleanup():
        logging.shutdown()
        _temp.cleanup()
    atexit.register(cleanup)

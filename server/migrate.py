"""服务端一次性迁移：账号角色列 + 会话表 + 审计表。在服务器执行一次。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


def migrate():
    with db.use_cloud():
        conn = db.get_conn()
        cols = {r["COLUMN_NAME"] if isinstance(r, dict) else r[0]
                for r in conn.execute(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'accounts'")}
        if "is_admin" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN is_admin TINYINT NOT NULL DEFAULT 0")
        if "status" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS web_sessions ("
            "token VARCHAR(64) PRIMARY KEY, owner VARCHAR(64) NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "expires_at TIMESTAMP NOT NULL, ip VARCHAR(45) DEFAULT '')")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audit_log ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY, actor VARCHAR(64) NOT NULL, "
            "action VARCHAR(64) NOT NULL, target VARCHAR(128) DEFAULT '', "
            "detail TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        conn.close()
    print("迁移完成：accounts.is_admin/status、web_sessions、audit_log")


if __name__ == "__main__":
    migrate()

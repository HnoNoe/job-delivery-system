"""统一字段数据库 —— 存储层。

字段名全局唯一、字段值可核对。原型用 SQLite 等价实现 MySQL，
生产环境可无缝切换 MySQL（表结构一致）。
"""
import sqlite3
import json
from pathlib import Path
import config


class Connection(sqlite3.Connection):
    """Commit/rollback and close on leaving a with block."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def get_conn():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    """建表（统一字段数据库的全部子表）。"""
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS user_records (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        l0 TEXT NOT NULL,          -- L0 身份骨架 JSON
        l1 TEXT NOT NULL,          -- L1 经历盘点 JSON {类型:条数}
        l3 TEXT NOT NULL,          -- L3 求职偏好 JSON
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS experience_items (
        exp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        exp_index INTEGER NOT NULL,   -- 经历序号 k (0-based)
        fields TEXT NOT NULL,         -- L2 字段 JSON
        embedding TEXT,               -- 经历向量 JSON
        UNIQUE(user_id, exp_index)
    );
    CREATE TABLE IF NOT EXISTS profile_weights (
        user_id INTEGER NOT NULL,
        exp_index INTEGER NOT NULL,
        weight REAL NOT NULL,         -- 经历权重 α_k
        PRIMARY KEY(user_id, exp_index)
    );
    CREATE TABLE IF NOT EXISTS jobs (
        job_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fields TEXT NOT NULL,         -- 岗位字段 JSON
        embedding TEXT                -- 岗位向量 JSON
    );
    CREATE TABLE IF NOT EXISTS user_jobs (
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, job_id)
    );
    CREATE TABLE IF NOT EXISTS user_job_scopes (
        user_id INTEGER PRIMARY KEY
    );
    CREATE TABLE IF NOT EXISTS delivery_attempts (
        task_id INTEGER PRIMARY KEY,
        day TEXT NOT NULL,
        state TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS target_jobs (
        job_id INTEGER PRIMARY KEY,
        score REAL NOT NULL,          -- 匹配分数 p
        entry_type TEXT,
        entry_addr TEXT
    );
    CREATE TABLE IF NOT EXISTS delivery_tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        job_name TEXT, unit_name TEXT, job_link TEXT,
        entry_type TEXT, entry_addr TEXT,
        resume_path TEXT,
        status TEXT DEFAULT '待生成',
        result TEXT DEFAULT ''       -- 投递状态 / 单位回应
    );
    CREATE TABLE IF NOT EXISTS job_field_map (
        task_id INTEGER PRIMARY KEY,
        fields TEXT NOT NULL          -- 该岗字段表 JSON
    );
    CREATE TABLE IF NOT EXISTS task_indicators (
        task_id INTEGER PRIMARY KEY,
        indicator TEXT NOT NULL       -- 写入指示 I_k JSON 列表
    );
    CREATE TABLE IF NOT EXISTS history_samples (
        sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_embedding TEXT,
        result INTEGER NOT NULL,      -- z ∈ {0,1}
        write_indicator TEXT,         -- I_k JSON 列表
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS job_centers (
        user_id INTEGER PRIMARY KEY,
        c_pos TEXT, c_neg TEXT        -- 岗位正/负中心 JSON
    );
    CREATE TABLE IF NOT EXISTS profile_pool (
        snap_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        weights TEXT,                 -- 经历权重快照 JSON
        user_vec TEXT,                -- 用户表示向量快照 JSON
        pos_center TEXT,              -- 岗位正中心快照 JSON
        neg_center TEXT,              -- 岗位负中心快照 JSON
        delivered_count INTEGER DEFAULT 0,  -- 累计投递数
        interview_count INTEGER DEFAULT 0,  -- 进面试数
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.execute("BEGIN IMMEDIATE")
    # Additive migrations: keep databases and historical tasks from older copies.
    for table, column, definition in (
        ("jobs", "active", "INTEGER NOT NULL DEFAULT 1"),
        ("delivery_tasks", "match_score", "REAL"),
        ("history_samples", "task_id", "INTEGER"),
    ):
        columns = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in columns:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS history_task_unique ON history_samples(task_id) WHERE task_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS tasks_user ON delivery_tasks(user_id)")
    conn.execute("INSERT OR IGNORE INTO user_jobs (user_id, job_id) SELECT DISTINCT d.user_id, d.job_id "
                 "FROM delivery_tasks d JOIN jobs j ON j.job_id=d.job_id "
                 "WHERE d.user_id NOT IN (SELECT user_id FROM user_job_scopes)")
    conn.execute("INSERT OR IGNORE INTO user_job_scopes SELECT DISTINCT user_id FROM delivery_tasks")
    conn.execute("UPDATE delivery_tasks SET match_score=(SELECT score FROM target_jobs t WHERE t.job_id=delivery_tasks.job_id) "
                 "WHERE match_score IS NULL")
    conn.commit()
    conn.close()


# ---- 字段值核对辅助 ----
def check_field_name(name):
    """字段名是否在统一字段集合内（白名单）。"""
    return name in _ALL_FIELDS


_ALL_FIELDS = set()
def _collect():
    import schema as s
    for lst in [s.L0_FIELDS, s.L1_TYPES, s.L2_FIELDS, s.L3_FIELDS,
                s.JOB_FIELDS, s.TASK_FIELDS, s.RESUME_ALLOWED_FIELDS,
                s.RESUME_ALLOWED_L2]:
        _ALL_FIELDS.update(lst)
_collect()

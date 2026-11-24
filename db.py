"""统一字段数据库 —— 存储层。

字段名全局唯一、字段值可核对。双后端：
- 默认 SQLite（单机/测试）：`config.DB_PATH`（可用环境变量 JOBDELIVERY_DB 覆盖）；
- 云端 MySQL（多机共用统一字段数据库）：环境变量 JOBDELIVERY_DB_URL=
  `mysql://user:pass@host:3306/dbname`，未设置时回退 `config.CLOUD_DB_URL`。

两种后端对业务代码暴露同一接口：`with db.get_conn() as conn:` +
`conn.execute(sql, params)`（`?` 占位符由本层翻译）、行同时支持 `row["字段"]` 与 `row[0]`。
"""
import os
import re
import sqlite3
import json
import threading
from pathlib import Path
import config

# 云端 MySQL 连接串（多机汇聚模式）。密码仅供本项目客户端使用，勿外泄。
# 特殊值 "sqlite" = 强制本机 SQLite（测试/离线场景）。
# 惰性解析：测试隔离会改环境变量，必须在使用时才读。
def _resolve_url():
    env_url = os.environ.get("JOBDELIVERY_DB_URL", "").strip()
    if env_url.lower() in ("sqlite", "local"):
        return ""
    return env_url or getattr(config, "CLOUD_DB_URL", "").strip()


DB_URL = _resolve_url()  # 导入时的快照（兼容直接引用）；运行时以 get_conn 解析为准


class Connection(sqlite3.Connection):
    """Commit/rollback and close on leaving a with block."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _translate(sql):
    """SQLite → MySQL 语句翻译（占位符与方言关键字）。"""
    sql = sql.replace("INSERT OR IGNORE", "INSERT IGNORE")
    sql = sql.replace("INSERT OR REPLACE", "REPLACE")
    if "PRAGMA" in sql:
        return "SELECT 1"
    # key 是 MySQL 保留字：裸标识符加反引号（FOREIGN KEY 是大写，不受影响）
    sql = re.sub(r"(?<![\w`])key(?![\w`])", "`key`", sql)
    # 替换引号串之外的 ? 为 %s
    parts = re.split(r"('[^']*')", sql)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("?", "%s")
    return "".join(parts)


class Row(dict):
    """同时支持 row[\"列名\"] 与 row[0]（下标按列顺序）的行类型。"""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _MySQLCursor:
    """已物化结果的游标：先取回全部行，支持多次消费同一快照。

    缓存命中时用同一份快照构造新游标，避免「游标只能读一遍」的陷阱。
    """
    def __init__(self, cur=None, snapshot=None):
        if snapshot is not None:
            self._rows, self._lastrowid, self._rowcount = snapshot
        else:
            self._rows = [Row(r) for r in cur.fetchall()]
            self._lastrowid = cur.lastrowid
            self._rowcount = cur.rowcount
        self._pos = 0

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        r = self._rows[self._pos]
        self._pos += 1
        return r

    def fetchall(self):
        r = self._rows[self._pos:]
        self._pos = len(self._rows)
        return list(r)

    def __iter__(self):
        return iter(self._rows)

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._rowcount


class MySQLShim:
    """pymysql 连接封装，向业务代码暴露 sqlite3.Connection 风格接口。"""
    def __init__(self):
        import pymysql
        from urllib.parse import urlparse, unquote
        u = urlparse(_resolve_url())
        self._conn = pymysql.connect(
            host=u.hostname, port=u.port or 3306,
            user=unquote(u.username or ""), password=unquote(u.password or ""),
            database=(u.path or "/").lstrip("/") or None,
            charset="utf8mb4", autocommit=False, connect_timeout=10,
            read_timeout=60, write_timeout=60,
            cursorclass=pymysql.cursors.DictCursor)
        # 跨公网 RTT 高达数百毫秒，而一次页面重跑会对同一批只读查询反复取数。
        # 进程内读缓存：SELECT 结果按 (语句, 参数) 复用；任何写语句整表清空缓存。
        self._rcache = {}
        # 事务脏标记：只有真正发过写语句才需要 COMMIT/ROLLBACK 网络往返，
        # 纯读页面零网络开销（每次 get_conn 的检查也跳过 ROLLBACK 包）。
        self._dirty = False

    @staticmethod
    def _is_select(sql):
        return sql.lstrip()[:6].upper() == "SELECT"

    def _reconnect(self):
        """断线重连并重置会话状态（缓存与脏标记随新会话重建）。"""
        try:
            self._conn.close()
        except Exception:
            pass
        self.__init__()

    @staticmethod
    def _lost(e):
        return getattr(e, "args", [0])[0] in (2002, 2003, 2006, 2013, 2055)

    def execute(self, sql, params=None):
        sql = _translate(sql)
        params = params or ()
        if not isinstance(params, tuple):
            params = tuple(params)
        if self._is_select(sql):
            snap = self._rcache.get((sql, params))
            if snap is not None:
                return _MySQLCursor(snapshot=snap)
        else:
            self._rcache.clear()
            self._dirty = True
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
        except Exception as e:
            if not self._lost(e):
                raise
            self._reconnect()
            cur = self._conn.cursor()
            cur.execute(sql, params)
        wrapped = _MySQLCursor(cur)
        if self._is_select(sql):
            self._rcache[(sql, params)] = (wrapped._rows, wrapped._lastrowid, wrapped._rowcount)
        return wrapped

    def executemany(self, sql, seq):
        self._rcache.clear()
        self._dirty = True
        cur = self._conn.cursor()
        cur.executemany(_translate(sql), seq)
        return _MySQLCursor(cur)

    def cursor(self):
        self._dirty = True  # 裸游标用途不可预期，按可能写入处理
        return self._conn.cursor()

    def commit(self):
        if self._dirty:
            self._conn.commit()
            self._dirty = False

    def rollback(self):
        if self._dirty:
            self._conn.rollback()
            self._dirty = False

    def close(self):
        # 连接归还给线程池而非真正断开：服务端仍挂着事务则回滚
        # （与「每次新建连接」语义一致，旧连接丢弃未提交改动），
        # 否则空闲事务长期占用元数据锁，会阻塞其他端的表结构变更。
        try:
            if self._conn.server_status & 0x0001:  # SERVER_STATUS_IN_TRANS
                self._conn.rollback()
                self._dirty = False
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


def is_mysql():
    return bool(_resolve_url())


def get_conn():
    url = _resolve_url()
    if url:
        # 线程级连接复用：Streamlit 每次交互重跑整页、查询数十次，
        # 若每次新建公网 TCP+鉴权（几十~几百毫秒）会明显卡顿。
        # 同一连接同时只归一个线程使用；断线自动重连。
        # 检出时若服务端仍挂着未提交事务（SELECT 在 autocommit=0 下也会开事务），
        # 必须回滚——否则空闲连接长期占用元数据锁，会阻塞其他端的表结构变更，
        # 并在多机共用时有锁堆积风险。server_status 是本地状态位，零网络开销。
        shim = getattr(_tls, "_shim", None)
        if shim is not None and not shim._conn.open:
            shim = None  # 本地套接字检查；断线由 execute 内重连兜底
        if shim is None:
            shim = MySQLShim()
            _tls._shim = shim
        try:
            if shim._conn.server_status & 0x0001:  # SERVER_STATUS_IN_TRANS
                shim._conn.rollback()
                shim._dirty = False
        except Exception:
            pass
        return shim
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


_tls = threading.local()


# ---- 建表 DDL ----
_TABLES_SQLITE = """
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
    CREATE TABLE IF NOT EXISTS hr_responses (
        resp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,     -- 关联投递任务
        platform TEXT DEFAULT '',     -- boss / zhilian / auto / manual …
        kind TEXT NOT NULL,           -- 已查看 / 邀面试 / 不合适 / 无回复 / 其他
        content TEXT DEFAULT '',      -- 备注或消息摘要（本地存储，不外传）
        content_hash TEXT,            -- 幂等去重（同任务同类型同内容不重复登记）
        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
        source TEXT DEFAULT 'manual', -- manual / auto
        FOREIGN KEY (task_id) REFERENCES delivery_tasks(task_id)
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
    CREATE TABLE IF NOT EXISTS hr_inbox (
        inbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,              -- 可空：未匹配到投递任务的会话
        platform TEXT DEFAULT '',
        company TEXT DEFAULT '',
        hr TEXT DEFAULT '',
        message TEXT DEFAULT '',
        kind TEXT DEFAULT '',         -- 分类结果
        msg_hash TEXT UNIQUE,         -- 幂等：同一会话同一消息只记一次
        first_seen TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS app_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    -- 账号体系：桌面端注册/登录。库中只存加盐 PBKDF2 哈希，不存明文密码。
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(64) UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """

_TABLES_MYSQL = _TABLES_SQLITE
_TABLES_MYSQL = _TABLES_MYSQL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                      "INT AUTO_INCREMENT PRIMARY KEY")
_TABLES_MYSQL = _TABLES_MYSQL.replace("key TEXT PRIMARY KEY", "key VARCHAR(191) PRIMARY KEY")
_TABLES_MYSQL = _TABLES_MYSQL.replace("key VARCHAR(191) PRIMARY KEY", "`key` VARCHAR(191) PRIMARY KEY")
_TABLES_MYSQL = _TABLES_MYSQL.replace("msg_hash TEXT UNIQUE", "msg_hash VARCHAR(191) UNIQUE")
_TABLES_MYSQL = _TABLES_MYSQL.replace("content_hash TEXT,", "content_hash VARCHAR(191),")
# MySQL 的 TEXT/BLOB 不允许带默认值：时间戳列改 VARCHAR + 表达式默认值（保持字符串语义）
_TABLES_MYSQL = _TABLES_MYSQL.replace(
    "TEXT DEFAULT CURRENT_TIMESTAMP", "VARCHAR(19) DEFAULT (CURRENT_TIMESTAMP)")
_TABLES_MYSQL = _TABLES_MYSQL.replace("TEXT DEFAULT '", "VARCHAR(64) DEFAULT '")


def _safe_index(conn, sql):
    try:
        conn.execute(sql)
    except Exception:
        pass  # MySQL 无 CREATE INDEX IF NOT EXISTS：已存在即跳过


def init_db():
    """建表（统一字段数据库的全部子表）。按当前后端选方言。"""
    conn = get_conn()
    if _resolve_url():
        _init_mysql(conn)
    else:
        _init_sqlite(conn)
    conn.close()


def _init_sqlite(conn):
    conn.cursor().executescript(_TABLES_SQLITE)
    conn.execute("BEGIN IMMEDIATE")
    _migrate(conn, sqlite=True)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS history_task_unique ON history_samples(task_id) WHERE task_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS tasks_user ON delivery_tasks(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS responses_task ON hr_responses(task_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS responses_dedup "
                 "ON hr_responses(task_id, kind, content_hash) WHERE content_hash IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS records_owner ON user_records(owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS pool_owner ON profile_pool(owner)")
    conn.commit()


def _init_mysql(conn):
    for stmt in [s.strip() for s in _TABLES_MYSQL.split(";") if s.strip()]:
        conn.execute(stmt)
    _migrate(conn, sqlite=False)
    # MySQL 不支持带 WHERE 的部分索引；唯一索引允许多个 NULL，语义等价
    _safe_index(conn, "CREATE UNIQUE INDEX history_task_unique ON history_samples(task_id)")
    _safe_index(conn, "CREATE INDEX tasks_user ON delivery_tasks(user_id)")
    _safe_index(conn, "CREATE INDEX responses_task ON hr_responses(task_id)")
    _safe_index(conn, "CREATE UNIQUE INDEX responses_dedup ON hr_responses(task_id, kind, content_hash)")
    _safe_index(conn, "CREATE INDEX records_owner ON user_records(owner)")
    _safe_index(conn, "CREATE INDEX pool_owner ON profile_pool(owner)")
    conn.commit()


def _migrate(conn, sqlite):
    """Additive migrations：保留旧库的历史任务。"""
    if sqlite:
        for table, column, definition in (
            ("jobs", "active", "INTEGER NOT NULL DEFAULT 1"),
            ("delivery_tasks", "match_score", "REAL"),
            ("history_samples", "task_id", "INTEGER"),
            ("user_records", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("delivery_tasks", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("profile_pool", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("profile_pool", "visibility", "VARCHAR(16) NOT NULL DEFAULT 'public'"),
        ):
            columns = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            if column not in columns:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))
    else:
        def _cols(table):
            rows = conn.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                                (table,)).fetchall()
            return {r[0] for r in rows}
        for table, column, definition in (
            ("jobs", "active", "INT NOT NULL DEFAULT 1"),
            ("delivery_tasks", "match_score", "DOUBLE"),
            ("history_samples", "task_id", "INT"),
            ("user_records", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("delivery_tasks", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("profile_pool", "owner", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("profile_pool", "visibility", "VARCHAR(16) NOT NULL DEFAULT 'public'"),
        ):
            if column not in _cols(table):
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))
    conn.execute("INSERT OR IGNORE INTO user_jobs (user_id, job_id) SELECT DISTINCT d.user_id, d.job_id "
                 "FROM delivery_tasks d JOIN jobs j ON j.job_id=d.job_id "
                 "WHERE d.user_id NOT IN (SELECT user_id FROM user_job_scopes)")
    conn.execute("INSERT OR IGNORE INTO user_job_scopes SELECT DISTINCT user_id FROM delivery_tasks")
    conn.execute("UPDATE delivery_tasks SET match_score=(SELECT score FROM target_jobs t WHERE t.job_id=delivery_tasks.job_id) "
                 "WHERE match_score IS NULL")


def ensure_cloud_database():
    """确保 JOBDELIVERY_DB_URL 指向的数据库存在（未指定库名时创建）。"""
    if not _resolve_url():
        return
    from urllib.parse import urlparse
    if urlparse(_resolve_url()).path.strip("/"):
        return  # 已指定库名（需预先建好）
    import pymysql
    from urllib.parse import unquote
    u = urlparse(_resolve_url())
    conn = pymysql.connect(host=u.hostname, port=u.port or 3306,
                           user=unquote(u.username or ""), password=unquote(u.password or ""),
                           charset="utf8mb4", connect_timeout=10)
    try:
        with conn.cursor() as c:
            c.execute("CREATE DATABASE IF NOT EXISTS jobdelivery "
                      "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
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

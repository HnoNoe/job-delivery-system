"""全局配置：数据库、嵌入、LLM、投递等参数。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 数据库（原型用 SQLite，生产可替换 MySQL，表结构一致）
DB_PATH = str(BASE_DIR / "data" / "jobdelivery.db")

# 嵌入
EMBED_DIM = 128
EMBED_MODEL = None

# 式三 匹配分数超参数（实施时选定，非负，二者不同时为 0）
W_S = 1.0
W_DELTA = 1.0

# 式四 指数倾斜强度（严格为正）
TAU = 1.0

# 式五 乘性更新步长（严格为正）
ETA = 0.5

# 投递重试
MAX_RETRY = 3

# ---------- 投递频率限制（防封号 + 防骚扰）----------
# 参考开源项目 boss-auto-job 的频率控制，超过会触发 Boss直聘封号(Code 32/36/37)
DAILY_SEND_LIMIT = 20   # 每日最多投递条数
BATCH_SEND_LIMIT = 5    # 单次最多投递条数

# 安全模式：默认开启。开启时「投递」只生成材料+招呼语，绝不自动点立即沟通/发消息给HR。
# 能力已在代码里（delivery.deliver_one + session.dpage_deliver/dpage_greet），
# 只有你明确把 SAFE_MODE 设为 False 才会真正执行自动投递。
SAFE_MODE = True

# 每轮投递间隔（秒），降低被封风险（即使关闭安全模式）
DELIVER_INTERVAL = 8

# 招呼语模板（占位符：{姓名} {学校} {专业} {岗位}）
GREETING_TEMPLATE = "您好，我是{姓名}（{学校}{专业}），看到贵司「{岗位}」岗位与我的经历很匹配，简历已发，希望能进一步沟通，期待您的回复。"

# ---------- 邮件投递（SMTP）----------
# 填 SMTP_USER/SMTP_PASSWORD 即真实发送；留空则写入本地发件箱 outbox/ 兜底
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = ""        # 发件邮箱，如 xxx@qq.com
SMTP_PASSWORD = ""    # 邮箱授权码（非登录密码）

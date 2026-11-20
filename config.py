"""全局配置：数据库、嵌入、LLM、投递等参数。"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("JOBDELIVERY_HOME", str(BASE_DIR))).expanduser().resolve()
DATA_DIR = RUNTIME_DIR / "data"
LOG_DIR = RUNTIME_DIR / "logs"
BROWSER_PATH = os.environ.get("JOBDELIVERY_BROWSER", "")
HEADLESS = os.environ.get("JOBDELIVERY_HEADLESS", "").lower() in ("true", "1", "yes")

# 检查 HR 回复时，会话列表由 WebSocket 推送，需要等它渲染（Boss 实测 ~10s）
CHAT_LOAD_WAIT = int(os.environ.get("JOBDELIVERY_CHAT_WAIT", "12"))

# 启动时自动检查 HR 回复（0 关闭）。冷却期内不会重复检查，避免每次刷新都开浏览器、触发平台风控。
AUTO_CHECK_REPLIES = os.environ.get("JOBDELIVERY_AUTO_CHECK", "1").lower() not in ("0", "false", "no")
AUTO_CHECK_COOLDOWN_MIN = int(os.environ.get("JOBDELIVERY_AUTO_CHECK_COOLDOWN", "60"))
# 发送招呼语后，等聊天记录出现该消息的确认时间（秒）
GREET_CONFIRM_WAIT = int(os.environ.get("JOBDELIVERY_GREET_CONFIRM_WAIT", "4"))
# 启动自动检查哪些平台（逗号分隔，默认只查 Boss；其它平台可在第⑥阶段手动检查）
AUTO_CHECK_PLATFORMS = [x.strip() for x in
                        os.environ.get("JOBDELIVERY_AUTO_CHECK_PLATFORMS", "boss").split(",")
                        if x.strip()]

# 检索时不弹出浏览器窗口：优先复用已打开的登录浏览器；
# 需要新开时把窗口移到屏幕外（仍是有头浏览器，指纹更真实，不易被判定为无头）。
# 设为 0/false 可恢复为“检索也弹窗”。
SEARCH_HIDDEN = os.environ.get("JOBDELIVERY_SEARCH_HIDDEN", "1").lower() not in ("0", "false", "no")

# ---------- 登录态检测 ----------
# 应用启动 / 页面刷新时自动检测各平台登录情况；联网探测只针对已有登录态的平台，
# 每次刷新最多一次请求/平台。设为 0 则只做本地检测（离线、零网络）。
LOGIN_CHECK_ONLINE = os.environ.get("JOBDELIVERY_LOGIN_CHECK", "1").lower() not in ("0", "false", "no")
LOGIN_CHECK_TIMEOUT = float(os.environ.get("JOBDELIVERY_LOGIN_CHECK_TIMEOUT", "6"))

# 数据库（原型用 SQLite，生产可替换 MySQL，表结构一致）
DB_PATH = str(Path(os.environ.get("JOBDELIVERY_DB", str(DATA_DIR / "jobdelivery.db"))).expanduser().resolve())

# 云端统一字段数据库（MySQL）。所有客户端机器留空 JOBDELIVERY_DB_URL 时默认连这里，
# 数据（用户记录 + 去重岗位池）全量汇聚到服务器，绘图/匹配都读云端。
# 可用环境变量 JOBDELIVERY_DB_URL=mysql://user:pass@host:3306/dbname 覆盖。
CLOUD_DB_URL = os.environ.get(
    "JOBDELIVERY_CLOUD_URL",
    "mysql://jobdelivery:%23%3EygZ%294.F%23U%3Fm4g@149.104.21.235:3306/jobdelivery")

# 生成式 AI 辅助（简历解析补全等，OpenAI 兼容接口）。
# 未配置或调用失败时相关功能自动回退离线规则解析，不影响主流程。
# 密钥不入库：优先环境变量，其次本地 secrets_local.py（git 忽略，打包时随 exe 内置）。
DEEPSEEK_API_KEY = os.environ.get("JOBDELIVERY_DEEPSEEK_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("JOBDELIVERY_DEEPSEEK_BASE", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("JOBDELIVERY_DEEPSEEK_MODEL", "deepseek-chat")
try:
    from secrets_local import DEEPSEEK_API_KEY as _LOCAL_KEY  # noqa: F401
    if _LOCAL_KEY:
        DEEPSEEK_API_KEY = _LOCAL_KEY
except ImportError:
    pass

# 嵌入
EMBED_DIM = 128
EMBED_MODEL = None

# 行业别名归并：同一组视为同一类（城市/行业硬约束与等级分共用）
# 需要更严格时把对应关键词删掉即可。
INDUSTRY_ALIASES = {
    "互联网": ["互联网", "计算机软件", "软件", "IT服务", "信息技术", "电子商务", "电商",
             "企业服务", "社交", "网络", "云计算", "大数据", "信息安全", "通信", "游戏"],
    "人工智能": ["人工智能", "AI", "智能硬件", "机器人", "机器学习", "计算机视觉",
              "自然语言", "算法"],
}

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
# 「全部投递」模式的间隔（更长，降低连续投递风控概率）
DELIVER_INTERVAL_ALL = int(os.environ.get("JOBDELIVERY_DELIVER_INTERVAL_ALL", "20"))

# ---------- 投递地址校验（防 SSRF / 个人信息外发到内网）----------
# 采集来的「投递入口地址」属于不可信数据：默认只允许 http/https 的公网地址。
# 本机回环放行是为了本地 Mock 测试站（127.0.0.1）；如无需要可设为 False。
ALLOW_LOOPBACK_ENTRY = os.environ.get("JOBDELIVERY_ALLOW_LOOPBACK_ENTRY", "1").lower() not in ("0", "false", "no")
# 内网/保留地址默认拒绝；确有内网投递系统时再显式打开。
ALLOW_PRIVATE_ENTRY = os.environ.get("JOBDELIVERY_ALLOW_PRIVATE_ENTRY", "0").lower() in ("1", "true", "yes")

# 招呼语模板（占位符：{姓名} {学校} {专业} {岗位}）
GREETING_TEMPLATE = "您好，我是{姓名}（{学校}{专业}），看到贵司「{岗位}」岗位与我的经历很匹配，简历已发，希望能进一步沟通，期待您的回复。"

# ---------- 邮件投递（SMTP）----------
# 填 SMTP_USER/SMTP_PASSWORD 即真实发送；留空则写入本地发件箱 outbox/ 兜底
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

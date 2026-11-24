# 设计：Web 客户端 + 管理端（服务端全家桶）

> 2026-11-24 立项。定位：**桌面端负责"做"（投递全流程，本地），Web 客户端负责"看"（数据/画像/岗位池，云端），管理端负责"治"（账号/内容/统计）。**
> 这是「补服务层」决策（见架构评审）的正式落地：第一个真实的服务端应用，跑在
> 团队服务器 `149.104.21.235` 上，全队浏览器即开即用，无需各自部署。

---

## 1. 为什么必须是服务端架构（而不是再做一个本地 Streamlit）

| 需求 | 本地 Streamlit | 服务端 Web |
|---|---|---|
| 换台电脑登录继续用 | ❌ 数据在本机 | ✅ 数据跟账号走 |
| 管理端（看别人、管全库） | ❌ 天然做不到 | ✅ |
| 统一入口发版，队友零部署 | ❌ 要发 exe | ✅ 改完即生效 |
| 手机/平板查看 | ❌ | ✅ 响应式页面 |

Streamlit 的会话模型和性能模型不适合多用户服务端，**技术选型收束：FastAPI + 服务端渲染（Jinja2 + Plotly）**。
不引入前后端分离（React/Vue）——团队规模和交付节奏匹配不了那套工程成本。

## 2. 总体架构

```
队友浏览器 ──HTTPS──▶ Caddy (自动 TLS, :443)
                          │
                    FastAPI 应用 (server/)
                    ├─ /auth      注册/登录/会话（复用 accounts 表，PBKDF2）
                    ├─ /app/*     Web 客户端（登录后）
                    ├─ /admin/*   管理端（role=admin）
                    ├─ /api/space 统一空间数据（unispace.build_space 服务端计算）
                    └─ 只连云端 MySQL（db.use_cloud）
                          │
                    云端 MySQL（现有 18 表，权限最小化账号）
                    
桌面端 exe（不变）──投递全流程──▶ 本地 SQLite ──cloud_sync/mydata──▶ 云端 MySQL
```

**边界纪律（写死）**：
- 服务端**不做真实投递**（服务器上没有浏览器、也不该有）；投递永远在桌面端。
- 服务端**不跑爬虫**；岗位入池来自各桌面端 cloud_sync.push。
- 服务端是**只加不改**：现有桌面端/本地流程一行不动。

## 3. 数据与权限模型

### 3.1 角色

| 角色 | 判定 | 能做什么 |
|---|---|---|
| 游客 | 未登录 | 看登录/注册页 |
| 用户 | accounts 表普通行 | 客户端全部功能 |
| 管理员 | accounts.is_admin = 1（新增列） | 客户端 + 管理端 |

`accounts` 加列：`is_admin TINYINT NOT NULL DEFAULT 0`、`status VARCHAR(16) NOT NULL DEFAULT 'active'`（active/disabled，封禁用）。

### 3.2 数据可见性（复用现有约定，补齐缺口）

| 数据 | 谁能看 | 谁能改 |
|---|---|---|
| 简历原文（云端 user_records） | 仅本人（owner 隔离，已有） | 仅本人 |
| 画像快照 | 本人全部；public 的他人可见向量/计数/标签 | 本人（发布/撤回已有） |
| 岗位池 jobs | 全队可读 | 任何人可推（去重幂等，已有） |
| 反馈/任务（若上云） | 仅本人 | 仅本人 |
| 账号表 | 管理端 | 管理端（禁用/设管理员/重置密码） |

### 3.3 安全基线（对照上轮评审的 P0 安全项，全部在这期闭合）

1. **MySQL 不再裸奔**：新增专用账号 `jobweb`，只授 `jobdelivery` 库的 SELECT/INSERT/UPDATE/DELETE，**撤销可建表/改表权限**（迁移用单独流程执行）；服务器安全组/防火墙只放行 22(SSH) 与 443。
2. **3306 不对公网开放**（改 bind-address / 防火墙），服务端与库同机走内网。
3. **HTTPS**：Caddy 反代自动签发证书（域名自备；过渡期可先 HTTP+IP 仅限团队，TLS 优先级最高）。
4. **会话**：服务端会话表（session_token 随机 256bit，httpOnly cookie，7 天滑动过期），替换现在的本地文件会话（桌面端保留本地文件方式不动）。
5. **密码**：沿用 PBKDF2（auth.py 逻辑抽到 server 共用）；登录失败限流（5 次/10 分钟/账号+IP）。
6. **注入与 XSS**：全部走参数化查询（现有 db 层已满足）；Jinja2 自动转义；Plotly 图走 JSON 渲染不走 HTML 拼接。

## 4. Web 客户端功能（/app）

| 页 | 功能 | 复用 |
|---|---|---|
| 首页仪表盘 | 我的投递统计、画像快照列表、待办（未标注反馈的任务数） | feedback.get_stats / get_profile_evolution |
| 我的简历 | 表单编辑 + PDF 导入（规则+DeepSeek）+ 保存云端 | resume_ai.smart_parse（已在） |
| 岗位池 | 浏览/搜索/筛选（城市/薪资/簇），"拉取到本地"提示 | cloud_sync.pull_jobs |
| 画像广场 | 现有广场的云端版：统一空间图（unispace 服务端算）+ 用户归属表 | unispace + viz.unified_space_chart |
| 我的画像 | 快照列表、发布/撤回、演进曲线 | mydata.push_profile / retract_profile |
| 投递工作台（只读视图） | 展示本机最近一次现场（需桌面端同步后可见）；引导语"投递请在桌面端执行" | pipeline.latest_result（本地；若本机无数据则显示提示） |

> 说明：工作台在 Web 端是**视图**不是**执行器**，避免"网页点了投递但服务器没浏览器"的幻觉。

## 5. 管理端功能（/admin）

| 页 | 功能 |
|---|---|
| 总览 | KPI：注册数/公开画像数/岗位池规模/今日活跃；统一空间缩略图（全图，无高亮） |
| 账号管理 | 列表（搜索/分页）、禁用/启用、设/撤管理员、重置密码（生成临时密码） |
| 内容治理 | 公开画像列表：查看标签与向量摘要、违规下架（retract，记审计日志）；岗位池去重统计、按 owner 看贡献、下架违规岗位（active=0） |
| 数据质量 | 统一字段强校验结果（verify_db_strict 的服务端版）、embedding 缺失率、最近同步时间线 |
| 审计日志 | 新表 `audit_log`：谁在何时做了什么治理动作（admin_only 动作全记） |
| 系统 | 版本号、依赖清单、服务器状态（磁盘/内存/DB 连接数） |

## 6. 服务端工程结构（新目录 server/，不碰现有模块）

```
server/
├── main.py            # FastAPI 入口：app 装配、中间件、静态/模板挂载
├── deps.py            # get_db / get_current_user / require_admin 依赖注入
├── security.py        # 会话签发/校验、限流、CSRF（表单同源校验）
├── templates/         # Jinja2（base.html + 各页）
├── static/            # CSS/JS（极简，主题沿用 theme.py 色板）
├── routers/
│   ├── auth.py        # 注册/登录/登出
│   ├── client.py      # 客户端各页
│   ├── space.py       # /api/space 统一空间 JSON（Plotly 前端渲染）
│   └── admin.py       # 管理端各页 + 治理动作
└── tests/
    └── test_api.py    # TestClient：注册登录/权限/空间接口/治理动作
```

**与现有代码的关系**：auth.py 的 PBKDF2 逻辑抽到 `security.py`（desktop 从原处 import 不变）；
mydata/unispace/cloud_sync **原样复用**（服务端只用云端函数）；db.py 不动。

## 7. 部署（149.104.21.235，Debian）

1. `apt` 装 `caddy`；`/etc/caddy/Caddyfile` 反代 `127.0.0.1:8000`，域名自动 TLS。
2. FastAPI 跑在 systemd 服务 `jobweb.service`（uvicorn，4 worker，自动重启）。
3. MySQL：建 `jobweb` 最小权限账号；迁移（is_admin/status/audit_log 建表）由一次性脚本执行。
4. 发布流：git push → SSH 拉取 → `pip install -r server/requirements.txt` → `systemctl restart jobweb`（Makefile 一条 `make deploy`）。
5. 日志：uvicorn access log + 应用 log → `journalctl`；审计日志独立表。

## 8. 分阶段交付

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P1 骨架** | server/ 骨架 + 注册登录 + 会话 + 权限依赖 + base 模板；deploy 脚本跑通 | 浏览器能注册登录，admin 能进管理端 |
| **P2 客户端** | 简历/岗位池/我的画像/广场统一空间 | 队友浏览器完成"注册→传简历→发布画像→看统一空间"全链 |
| **P3 管理端** | 账号治理/内容治理/审计/数据质量 | 管理员能禁用账号、下架画像、看审计 |
| **P4 打磨** | 限流调优、HTTPS、README 部署文档、回归接入 verify 套件 | 上轮评审 P0 安全项全部闭合 |

## 9. 风险与不做的事

- **不做**：真实投递上服务端、服务端爬虫、前后端分离重构、移动端 App。
- **风险**：服务器 IP 直连无域名时 TLS 证书签不了——过渡期团队内网 HTTP 先行，但管理端入口必须尽快上域名+HTTPS（密码明文过网不可接受）。
- **桌面端与 Web 端简历双写**：桌面存本地、Web 存云端——**收束方案：Web 端的简历编辑写入云端为准，桌面端"从云端载入"覆盖本地**（mydata.load_resume 已有），发布画像时以云端简历为标签来源。一句话：**简历的"云端副本"是共享真相，本地库是工作副本**，方向单向（云→本同步由用户手动拉取），不自动双向。

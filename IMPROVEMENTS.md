# 改进说明（相对 `main` 的完整变更）

> 分支：`improvement/login-status-portable`
> 基线：`HnoNoe/job-delivery-system@main`（`1312167`）
> 目标：修复阻断完整流程的问题，补齐登录态检测与检索体验，并提供免安装的单文件便携版。

---

## 一、变更概览

| 类别 | 内容 | 关键文件 |
|---|---|---|
| 环境与启动 | 依赖补全、虚拟环境探测、端口/健康检查、跨平台启动脚本 | `requirements.txt`、`start.py`、`start.bat`、`start.sh`、`setup_env.py`、`run_checks.py` |
| 流程正确性 | 状态机、原子事务、去重与更正、重复投递防护、统计口径 | `delivery.py`、`feedback.py`、`generation.py`、`schema.py`、`db.py` |
| 安全加固 | 入口地址校验、cookie 去 pickle、HTML/PDF 转义、会话隔离 | `delivery.py`、`session.py`、`theme.py`、`generation.py`、`config.py` |
| 平台与登录 | 新增登录态检测模块，启动/刷新自动检测，联网校验可选 | `login_status.py`、`platforms.py`、`app.py` |
| 检索体验 | 检索静默（不弹窗）、结果表内点击岗位名直达原页面 | `session.py`、`theme.py`、`app.py` |
| 便携版 | PyInstaller 单文件 exe，双击即用 | `portable_launcher.py`、`portable.spec`、`build_portable.bat` |
| 测试 | 38 个回归用例 + 7 组离线校验 + Mock 全链路 + 真实浏览器冒烟 | `tests/test_regressions.py`、`verify_*.py`、`verify_browser.py`、`mock_e2e.py` |

前一轮的 42 项修复（详见 `BUGFIX_REPORT.md`）已包含在本分支中；本轮在其之上补齐了复核发现的缺口。

---

## 二、本轮重点修复

### 1. 「待核实」任务可被降级，导致重复投递（高）

- 现象：API 超时/浏览器提交结果不确定时任务进入 `待核实`（可能已发出），但重新生成简历会把状态改回 `待检查` → `待投递`，用户可再次投递同一岗位。
- 修复：新增 `schema.TASK_LOCKED = [投递中, 待核实, 已投递, 已完成]`；`generation` / `prepare_batch` / UI 重新生成按钮全部拦截锁定状态。
- 回归：`test_uncertain_task_is_not_downgraded_and_cannot_be_resent`。

### 2. 检索结果为 0 时原因被吞掉

- 现象：浏览器句柄失效时 `dpage_search` 捕获异常返回 `[]`，界面统一显示「登录态可能失效」，误导排查。
- 修复：新增 `session.last_search_error()`，把真实原因（浏览器被占用 / 登录失效 / 风控拦截 / 接口无响应）带到第③步与 `data/search_debug_<平台>.log`。

### 3. 应用重启后丢失浏览器，检索直接失败

- 修复：记录调试端口（`.devtools_port` + Chrome 自带 `DevToolsActivePort`），重启后**接管仍在运行的浏览器**；死句柄自动丢弃并重启一次；启动后校验窗口是否真的起来。

### 4. 采集入口地址未校验（SSRF / 个人信息外发）

- 修复：`delivery.checked_entry_url()` 仅允许 http/https、拒绝带凭据 URL、拒绝内网/保留地址（回环默认放行用于本地 Mock，可用环境变量调整）。

### 5. 检索弹窗 & 结果不可点击

- 检索期间把浏览器窗口隐藏（Windows `SW_HIDE`），需要新开时窗口置于屏幕外；点「打开登录页」自动显示并移回屏幕。
- 第③步结果由 `st.dataframe` 改为 HTML 表格：**岗位名称是真实链接**（`target=_blank`），其余字段完整转义；无合法链接时降级为纯文本。
- 开关：`JOBDELIVERY_SEARCH_HIDDEN=0` 恢复旧行为。

### 6. 登录态检测（新增模块）

- 新增 `login_status.py`：应用启动 / 页面刷新自动检测 6 个平台，输出分级结论：
  `logged_in` / `saved` / `expired` / `blocked` / `absent` / `unknown`。
- 本地判断：cookie 文件、关键 cookie（智联 `at`、拉勾 `LGRID`）、cookie 过期时间、浏览器登录目录。
- 联网校验（可选）：只对已有登录态的平台发一次短超时请求，按跳转登录页 / 401/403 / 验证页分类；结果缓存 5 分钟，F5 重新检测。
- 侧栏与第②步统一展示状态徽章 + 原因 + 「重新检测」按钮。
- 开关：`JOBDELIVERY_LOGIN_CHECK=0` 完全离线；`JOBDELIVERY_LOGIN_CHECK_TIMEOUT` 调整超时。

### 7. 单文件便携版

- `portable_launcher.py` + `portable.spec`：PyInstaller onefile，内置 Streamlit 静态资源、Plotly/Pandas/ReportLab/PDF 解析/DrissionPage/Selenium。
- 启动：自动选空闲端口、健康检查通过后再打开浏览器；`--check` 打印依赖与浏览器路径。
- 数据落在 exe 同目录（不可写时回退 `%LOCALAPPDATA%\JobDeliverySystem`）。
- 实测：Windows 11 / Python 3.13 构建产物 **130 MB**，冷启动约 **13 秒**，中文+空格路径可用。

---

## 三、验证方式

```powershell
# 全部离线回归（38 用例 + 7 组校验 + Mock 全链路）
.venv\Scripts\python.exe run_checks.py

# 真实浏览器冒烟（本地 Mock：登录 / 旁听接口 / 重启后接管）
.venv\Scripts\python.exe verify_browser.py

# 便携版自检
dist\JobDeliverySystem.exe --check
```

当前结果：`run_checks.py` 全绿；`verify_browser.py` 输出 `login + listener search (3 jobs), re-attach (3 jobs)`；便携版页面实测渲染正常（hero、6 步向导、18 个状态牌）。

---

## 四、兼容性与行为变化

| 项目 | 变化 | 影响 |
|---|---|---|
| `profile.py` | 改名 `user_profile.py` | 避免遮蔽标准库 `profile`；外部若直接 `import profile` 需改为 `user_profile` |
| 任务状态 | 新增 `投递中 / 待核实`，锁定状态不可重生成 | 旧数据自动迁移，`match_score` 回填 |
| 检索 | 默认不弹浏览器窗口 | 可用 `JOBDELIVERY_SEARCH_HIDDEN=0` 恢复 |
| 检索结果表 | `st.dataframe` → HTML 表格 | 失去列排序/筛选，但岗位名可点击；后续可加过滤框 |
| 投递入口 | 非公网地址默认拒绝 | 内网投递系统需 `JOBDELIVERY_ALLOW_PRIVATE_ENTRY=1` |
| 依赖 | `streamlit>=1.46,<2`；浏览器依赖拆到 `requirements-browser.txt` | 首装更轻；`plotly` 已显式声明 |

---

## 五、已知限制

1. 真实平台适配仍需实测：Boss 依赖登录态（无头会被识别为爬虫，已改用「有头+隐藏窗口」）；智联/拉勾/猎聘/前程无忧的选择器多数已过期，详见 `CRAWLER_AUDIT.md`。
2. 登录态联网校验是启发式：平台返回验证页时给 `blocked`（不误判为未登录），不代表账号一定有效。
3. 便携版未签名，Windows SmartScreen 可能提示；真实平台仍需要本机 Chrome/Edge。
4. 检索结果表暂不支持排序/筛选（可点击链接优先）。
5. 单文件版每次启动需解压依赖（约 10–13 秒）。

---

## 六、文件清单（相对基线新增/改名）

- 新增：`login_status.py`、`runtime_paths.py`、`browser_runtime.py`、`user_profile.py`、`portable_launcher.py`、`portable.spec`、`build_portable.bat`、`setup_env.py`、`run_checks.py`、`test_support.py`、`verify_browser.py`、`tests/test_regressions.py`、`requirements-browser.txt`、`requirements-build.txt`、`requirements-tested.txt`、`start.sh`、`.gitattributes`、`.github/workflows/tests.yml`
- 改名：`profile.py` → `user_profile.py`
- 文档：`BUGFIX_REPORT.md`、`BUGFIX_REVIEW.md`、`CRAWLER_AUDIT.md`、`docs/`（界面截图）
- 其余为既有文件的修复与增强（`app.py`、`delivery.py`、`feedback.py`、`session.py`、`matching.py`、`theme.py` 等）。

---

## 七、上线建议

1. 合并前在真实账号上跑一次：扫码登录 Boss → 检索 → 准备材料 → 人工确认投递 → 标注结果 → 重新匹配。
2. 保留 `SAFE_MODE=True` 默认值；批量投递前确认平台规则与自身风险。
3. 便携版建议由维护者重新打包并用团队证书签名后再对外发布。

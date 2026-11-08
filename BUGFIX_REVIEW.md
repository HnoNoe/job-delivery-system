# BUGFIX_REPORT.md 复核报告

- 复核日期：2026-11-07
- 复核对象：`BUGFIX_REPORT.md` 声称的 42 项修复（工作区未提交改动）
- 复核人环境：Windows 10、Python 3.13.5、项目 `.venv`（streamlit 1.66.1 / plotly 7.1.0 / numpy 2.5.4 / pandas 3.1.0）、本机 Chrome
- 结论：**42 项修复绝大多数成立**（逐条比对代码 + 全量回归 + 真实浏览器冒烟 + 全 UI 流程）。复核中发现 **4 个遗留缺陷**（其中 1 个可导致重复投递），已在本次复核中修复并补测试；另有 8 项未覆盖风险列在第四节。

---

## 一、验证方法与结果

| 验证项 | 命令 | 结果 |
|---|---|---|
| 新增回归用例 | `.venv\Scripts\python.exe -m unittest discover -s tests -v` | **35 passed**（原 32 + 本次补 3） |
| 全量检查 | `.venv\Scripts\python.exe run_checks.py` | **All checks passed**（35 用例 + 7 组 verify + mock_e2e） |
| 公式/再匹配/可视化/健康度 | `verify_*.py` | 全部 PASS |
| Mock 全链路 | `mock_e2e.py` | 检索 3 岗 → 投递 3/0 → 反馈 → 画像快照 1，通过 |
| 真实浏览器冒烟 | `verify_browser.py` | **通过**：真实 Chrome 完成本地 Mock 登录、保存 cookie、监听接口取到 3 个岗位 |
| 启动器 | `.venv\Scripts\python.exe start.py` | `/_stcore/health` 返回 `ok`，端口就绪后才开浏览器 |
| 全 UI 流程（AppTest 实点） | 自定义探针（未提交） | 确认信息 → 检索 → 准备材料(3 任务) → 查看材料 → 确认手动投递 → 进面试 → 重新匹配(3) → 重新开始，**全程无异常** |
| 智联采集器 demo | `python main.py --demo -m 20` | 未装 Playwright 也可用，Excel/CSV 正常生成 |

> 说明：`run_checks.py` 的退出码、断言是否真的有效、测试是否隔离都实际检查过（见 B42 项），不是只看“显示 PASS”。

---

## 二、复核发现的问题（已修复）

### D1【重要｜重复投递风险】「待核实」任务会被降级回「待投递」

- 场景：API 超时 / 浏览器提交结果不确定时，任务进入 `待核实`（**可能已经发到平台**）。
- 原行为：`generation.generate_resumes` 只拦截 `已投递`；`delivery.prepare_batch` 只排除 `已投递`。于是用户点「🔄 按勾选重新生成简历」→ 状态回到 `待检查` → `prepare_batch` 置 `待投递` → **可再次投递**，造成同一岗位重复申请。
- 复现证据（复核时实测）：
  ```
  after timeout: 待核实
  regenerated: 1 -> 待检查
  prepare_batch report: 1 -> 待投递     ← 被降级，可二次发送
  ```
- 修复：
  - `schema.py` 新增 `TASK_LOCKED = ["投递中", "待核实", "已投递", "已完成"]`；
  - `generation.generate_resumes` 跳过锁定状态（原只跳过已投递）；
  - `delivery.prepare_batch` 过滤锁定状态，不再降级；
  - `app.py` 重新生成按钮对锁定状态禁用；
  - 新增用例 `test_uncertain_task_is_not_downgraded_and_cannot_be_resent`。

### D2【流程阻断】Mock 站无法检索带空格的多词关键词，默认流程走不到第④步

- 现象：第③步默认关键词是 `Python 后端`，Mock 站把整串当一个词做子串匹配 → **0 个岗位** → 第④步按钮锁死，看起来像“系统坏了”。
- 实测：`"后端"` → 3 岗；`"Python 后端"` → **0 岗**。
- 修复：`mock_site._api_search` 按空白/逗号拆词，任一命中即返回（贴近真实搜索的相关度语义），并在岗位名、技能、行业、标签里查找；新增用例 `test_mock_search_accepts_multi_token_keyword`。
- 复核后：默认关键词可正常返回 3 个岗位，全 UI 流程可走通。

### D3【安全】投递入口地址未校验（SSRF / 个人信息外发到内网）

- 根因：`entry_addr` 来自采集到的岗位数据，属不可信输入；`_deliver_api` 直接 `POST` 姓名/手机/邮箱/学校/专业/简历路径，`_deliver_web` 直接打开并自动填表提交。
- 修复：`delivery.checked_entry_url()`：
  - 仅允许 `http`/`https`（拒绝 `file:` 等）；
  - 拒绝带账号密码的 URL；
  - 解析主机并拒绝内网/保留/链路本地地址，**回环默认放行**（本地 Mock 需要），可用 `JOBDELIVERY_ALLOW_LOOPBACK_ENTRY=0` 关闭；确有内网系统时用 `JOBDELIVERY_ALLOW_PRIVATE_ENTRY=1` 显式打开；
  - API 与 Web 表单两条投递路径都走校验。
- 新增用例 `test_entry_url_validation`（`file://`、`ftp://`、`10.0.0.5`、带凭据 URL、非法串全部被拒）。

### D4【安全/展示】岗位链接与统计口径

- `app.py` 第⑤步「打开岗位详情」原来直接渲染采集来的链接，可被 `javascript:` 等 scheme 利用 → 改为仅 `http(s)` 才渲染，其余提示“链接格式无效，已忽略”。
- 第⑥步投递结果饼图原来把 `result` 里的**材料包路径文本**当成一种“结果” → 改为只统计 `进面试/未进面试`（`feedback.RESULTS`）。

### D5【易用性】未映射平台时的报错误导

- 非安全模式下，非平台页面（无 `COOKIE_DOMAINS` 映射）投递原来提示“登录浏览器未打开，无法投递”，实际原因是不支持该入口 → 改为“该岗位不在已支持自动投递的平台内，请手动投递（材料包已生成）”。

---

## 三、42 项逐条核对

状态说明：✅ 代码已按报告实现且本次实测覆盖；⚠️ 实现成立但有前提/未完全验证；❓ 本机无对应环境，只能静态核对。

| 编号 | 复核结论 | 依据 |
|---|---|---|
| B01 requests 显式声明 | ✅ | `requirements.txt` 含 `requests>=2.31,<3` |
| B02 Streamlit 最低版本 | ✅ | `streamlit>=1.46,<2`；1.66.1 实测通过 |
| B03 浏览器依赖拆分 | ✅ | `requirements-browser.txt`；`session` 内延迟导入、缺包给提示 |
| B04 启动器跨平台找解释器 | ✅ | `start.py:find_python` 覆盖 `Scripts`/`bin`/当前解释器 |
| B05 venv 重建/修复 | ⚠️ | `setup_env.py` 存在且逻辑正确；本机未重建验证 |
| B06 `main.py web` 路径 | ✅ | 统一走 `start.main(["--foreground"])` 与绝对 app 路径 |
| B07 端口占用识别 | ✅ | `available_port` + `/_stcore/health` 探活；用例 `test_occupied_port_chooses_another` |
| B08 子进程/日志处理 | ✅ | 轮询 `proc.poll()`、写 `logs/streamlit.*.log`、`--check/--no-browser/--foreground`；实测启动成功 |
| B09 PDF 中文字体可移植 | ✅ | 改用 `STSong-Light`；PDF 中文抽取用例通过 |
| B10 简历路径相对化 | ✅ | `resume_path` 相对 `RUNTIME_DIR`，`resolve_resume` 兼容旧绝对路径；用例覆盖 |
| B11 文件名清洗 | ✅ | `runtime_paths.safe_filename`；非法公司名用例通过 |
| B12 `profile.py` 遮蔽标准库 | ✅ | 重命名 `user_profile.py`，导入全部更新；`cProfile` 用例通过 |
| B13 去掉 lxml 强依赖 | ✅ | 统一 `html.parser`；HTML 采集用例通过 |
| B14 `collect_from_sources` 空实现 | ✅ | 函数体已恢复，真实本地 HTML 采集用例通过（我上一轮报告的潜伏 bug 已修好） |
| B15 相对/协议相对/file URI | ✅ | `urljoin` + `url2pathname`；用例覆盖 `../` 与中文空格路径 |
| B16 搜索 URL 编码 | ✅ | `platforms.search_url` 统一 `quote`；`C++ & Python` 用例 |
| B17 Boss 城市码 | ✅ | 支持城市名/编码/“市”后缀，未知城市抛错；用例覆盖 |
| B18 未知平台/单平台异常 | ✅ | `loop` 逐平台 try/except；用例覆盖未知平台 |
| B19 仅“已保存 cookie”算登录 | ✅ | `is_active = has_session`；用例覆盖“浏览器开着但未保存” |
| B20 JSON 会话 + 旧 pickle 白名单 | ✅ | 自定义 `Unpickler` 拒绝任意类；损坏文件返回未登录（用例） |
| B21 跨平台浏览器/端口 | ✅ | `browser_runtime.find_browser`、随机空闲端口；真实 Chrome 冒烟通过 |
| B22 去掉强杀浏览器 | ✅ | 已无 `taskkill /F`；锁库时提示用户自行关闭 |
| B23 检索不再删历史岗位 | ✅ | `jobs.active` + 迁移；`test_history_survives_new_search` 通过 |
| B24 重复岗位复用 ID | ✅ | 按规范化字段去重；`test_repeated_search_...` 通过 |
| B25 岗位范围按用户隔离 | ✅ | `user_jobs`/`user_job_scopes`、任务保存 `match_score`；用例通过 |
| B26 反馈去重与更正 | ✅ | 同任务唯一 + 全量重算；用例验证改判后回到 `[0.5,0.5]` |
| B27 反馈原子性 | ✅ | 先校验后写、事务；`test_invalid_feedback_is_atomic` 通过 |
| B28 统计口径 | ✅ | 只统计真实标签与已投递；`test_materials_are_not_feedback_or_sends` 通过 |
| B29 安全模式不伪装已投递 | ✅ | 查看材料不改状态 + 独立的「确认已手动投递」；用例 + 全 UI 流程验证 |
| B30 HTTP/SMTP 失败不报成功 | ✅ | 显式抛错；503/业务码/超时/SMTP 失败用例均通过 |
| B31 表单/聊天如实反馈 | ✅ | 提交按钮与成功文案校验、缺失即失败；聊天未确认返回不确定 |
| B32 超时不重试 + 事务占用 | ✅ | `DeliveryUncertain` 不重试；`BEGIN IMMEDIATE` 占位；并发预算用例通过 |
| B33 空 task_ids / limit / 队列 | ✅ | 空集不投、`min(limit, BATCH_SEND_LIMIT)`、只取待投递；用例通过 |
| B34 已投递不可重生成 | ✅ | 后端跳过 + 页面禁用；**本次扩展到 待核实/投递中/已完成（见 D1）** |
| B35 同名经历/键冲突 | ✅ | 键带 `#idx`、控件 key 带索引、从尾部拆字段；用例通过 |
| B36 时间字段/转义 | ✅ | `RESUME_ALLOWED_L2` 含时间起止、PDF 转义、卡片 HTML 转义；用例通过 |
| B37 PDF 只解析一次 | ✅ | 内容哈希记录；AppTest 用例验证手改不被覆盖 |
| B38 确认指纹/数据快照 | ✅ | `confirmed_info` 指纹 + `prepared_user_data`；UI 用例通过 |
| B39 重置与重新检索清理 | ✅ | 完整清理 + 新检索清旧视图 + 重生成同步材料包；UI 探针实测 |
| B40 输入校验 | ✅ | 类型/计数/真实日期；用例覆盖 `2025-02-31` 等 |
| B41 数学边界 | ✅ | 空向量、log-space 倾斜、`logistic` 开区间、有限性校验；用例通过 |
| B42 测试隔离/退出码/探针 | ✅ | `test_support` 临时 home+库、随机端口、`run_checks` 汇总退出码；实测隔离生效 |
| 其他：跨平台脚本/行尾/JOBDELIVERY_HOME/SMTP 环境变量 | ✅ | `.gitattributes`、`start.sh`、`config` 环境变量；本机 Windows 路径生效 |

---

## 四、未修复的剩余风险（建议后续处理）

| 编号 | 风险 | 说明与建议 |
|---|---|---|
| R1 | Boss 非安全模式每次都进「待核实」，批量投递首条即停 | `session.dpage_greet` 保守地永远返回 False；而 `deliver_batch` 把“人工核对”也算作风控熔断词。建议把“风控/登录失效”与“结果不确定”分为两类停止原因，后者继续下一条但计入待核实 |
| R2 | `target_jobs` 无 `user_id`（全局表） | 多用户会互相覆盖分数；当前打分在内存、统计走 `delivery_tasks.match_score`，影响有限。若做多用户，应加 `user_id` 主键 |
| R3 | `deliver_batch(task_ids=None)` 取全库待投递 | CLI `main.py batch` 无用户上下文，共用机器可能投到别人的任务。建议 CLI 增加 `--user` |
| R4 | LLM `base_url` 未校验、prompt 未对岗位文本定界 | 可指向任意地址并携带 API key；岗位描述属不可信文本，建议加 https/主机白名单与“数据区”分隔 |
| R5 | 上传 PDF 无大小/页数上限 | 大文件/畸形 PDF 会拖垮页面或解析器；建议限制体积与页数 |
| R6 | Selenium 旧登录路径 (`get_logged_in_browser`) 仍在 | 与 DrissionPage 主路径并存，cookie 注入逻辑重复，容易混淆 |
| R7 | CI 配置未实际运行 | `.github/workflows/tests.yml` 只在本机写好，未 push 运行；Linux/macOS 仍是“代码已适配、未实测” |
| R8 | `HANDOFF.md` 过期 | 仍写 `profile.py`、`C:/Users/Camevian/...` 旧路径；已在文件头加“历史文档”说明并改掉文件名/路径 |

---

## 五、本次复核的改动清单（均未提交 Git）

| 文件 | 改动 |
|---|---|
| `schema.py` | 新增 `TASK_LOCKED`（投递中/待核实/已投递/已完成） |
| `generation.py` | 锁定状态不再重生成（原只拦已投递） |
| `delivery.py` | `prepare_batch` 不降级锁定任务；新增 `checked_entry_url`；API/Web 投递前校验入口地址；未映射平台给出正确提示 |
| `config.py` | `ALLOW_LOOPBACK_ENTRY` / `ALLOW_PRIVATE_ENTRY` 环境变量开关 |
| `mock_site.py` | 多词关键词按词拆开匹配（修复默认关键词 0 结果） |
| `app.py` | 投递按钮按状态给出正确文案/禁用；重新生成按钮按锁定状态禁用；岗位链接仅允许 http(s)；结果饼图只统计真实反馈 |
| `tests/test_regressions.py` | 新增 3 个用例（待核实不可降级、入口地址校验、Mock 多词关键词），共 35 个 |
| `HANDOFF.md` | 标注历史文档、修正 `user_profile.py` 与旧本机路径 |

**未改动**：42 项修复的主体逻辑、五公式、数据库结构（仅新增常量）、UI 版式。

---

## 六、复核结论

- GPT 那轮修复**不是表面功夫**：测试隔离、状态机、原子性、路径可移植、安全模式语义都实打实落地，42 项里 40 项可直接确认，2 项（B05、CI）受环境限制只能静态核对。
- 但它**没有覆盖“不确定态”的完整生命周期**（D1 可导致重复投递）、**没有验证默认 UI 关键词在 Mock 站的可达性**（D2 让默认流程走不通）、**没有处理采集入口地址的信任边界**（D3 SSRF）。
- 本次复核已修掉这 4 类问题并补了回归用例；当前 `run_checks.py`、真实浏览器冒烟、全 UI 流程均为绿。

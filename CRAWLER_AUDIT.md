# 各平台爬虫 / 投递通道可用性检查报告

- 检查日期：2026-11-07
- 检查范围：`platforms.py` 注册的 6 个平台（mock / boss / zhilian / lagou / liepin / job51）的**检索**与**投递**两条链路
- 检查方式：
  1. **代码路径审计**：每个平台走「浏览器旁听接口」还是「HTML 解析」、需要什么登录态、投递是否有对应实现；
  2. **本机实测**：本地 Mock 站全链路（检索 + 投递）；Selenium HTML 回退路径用 Mock 打通；
  3. **真实站点轻量探测**：每个平台**仅 1~2 次无登录请求**（不翻页、不带账号 cookie、不触发投递），另用无头浏览器各加载 1 次搜索页，检查配置的 CSS 选择器是否还存在。
- 合规说明：未登录任何账号、未发送任何投递、未批量抓取；探测结果只用于判断适配器是否过期。

---

## 一、结论速览

| 平台 | 检索链路 | 实测结果 | 投递链路 | 结论 |
|---|---|---|---|---|
| **mock**（本地） | 接口 + 浏览器旁听 + Selenium HTML | ✅ 3 个岗位；Selenium 路径也 3 个；投递 3 条 | ✅ API 自动投递 | **完全可用**（联调用） |
| **boss** | 浏览器旁听 `joblist.json`（不用 DOM） | ⚠️ 无登录态被重定向到 `web/passport/zp/security.html`，无法在未登录下验证 | ✅ 唯一实现了自动投递（`a.btn-startchat` + `.chat-input textarea`） | **需登录实测**；设计正确，选择器可能随改版失效 |
| **zhilian** | Selenium 抓 HTML（无 api_field_map） | ❌ 无头浏览器被 `Security Verification` 拦截；配置选择器 0 命中 | ❌ 无适配 | **当前不可用**，需真实浏览器 + 验证码 + 重写选择器 |
| **lagou** | 旁听 `positionAjax.json` | ❌ 出现滑块验证页；requests 调 API 返回 **WAF 页面**（非 JSON） | ❌ 无适配 | **当前不可用**，需登录后实测旁听路径 |
| **liepin** | Selenium 抓 HTML（无 api_field_map） | ❌ 页面能开（40 张卡片），但配置 `div.job-list-item` **0 命中**，实际是 `jobCardPcContainer` | ❌ 无适配 | **选择器已过期**，且现用类名是哈希类，需重写 |
| **job51** | 旁听 `search-pc` | ❌ 配置 `div.joblist_item`（下划线）0 命中，实际是 `div.joblist-item`（连字符）；requests 调 API 返回 **WAF 页面** | ❌ 无适配 | **差一个字符即可命中**（前提是登录旁听路径可用） |

一句话：**只有 Mock 是真正全链路可用的；真实平台里只有 Boss 具备自动投递实现，但必须登录实测；其余 4 家当前检索适配器过期或被反爬拦截，且都没有投递实现。**

---

## 二、逐平台证据

### 1. mock（本地测试站）— ✅ 完全可用

- 检索：`crawler.search_via_requests` 返回 3 个岗位（`mock_e2e.py` 实跑）；
- 检索（Selenium HTML 回退路径 `crawler.search_platform`）：实跑返回 3 个岗位，字段映射正确（岗位名/公司/城市/链接）；
- 投递：`delivery.deliver_batch` 成功 3/0，Mock 站记录到 3 条投递；
- 说明：Mock 只复现结构，不代表真实平台的反爬能力。

### 2. boss（BOSS直聘）— ⚠️ 需登录，设计正确

- 代码路径：`session.dpage_search()` 用 DrissionPage **旁听浏览器自己发的 `/wapi/zpgeek/search/joblist.json`**，不自己发请求、不解析 DOM（`session.py:472`）——这是对抗 Boss 反爬的正确做法。
- 实测（无登录）：
  - 直接 GET 搜索页：HTTP 200、9KB、无 `li.job-card-wrapper`、无 `__INITIAL_STATE__` → 是 SPA 空壳；
  - 无头浏览器加载：被重定向到 `https://www.zhipin.com/web/passport/zp/security.html`（标题“请稍候 - BOSS直聘”）。
  - 结论：**未登录无法验证选择器/接口**；需要你的账号扫码后才能确认真实可用性。
- 投递：`session.dpage_deliver()` 点击 `a.btn-startchat`，`dpage_greet()` 写入 `.chat-input textarea` 并发 Enter；这是仓库里**唯一**的自动投递实现。
- 已知限制（上一轮修复遗留）：
  - `dpage_greet` 永远返回“未确认”，所以每次都会落到「待核实」，需要人工确认；
  - `deliver_batch` 把“人工核对”也当作熔断词 → 批量投递第一条就停。
- 判定：**结构可用、需登录实测**；上线前必须用真号验证 4 个点：搜索接口字段、城市码、详情页按钮、聊天框选择器。

### 3. zhilian（智联招聘）— ❌ 当前不可用

- 代码路径：`platforms["zhilian"]` 没有 `api_field_map` → `dpage_search` 回退到 `crawler.search_platform`（Selenium + `html.parser` + CSS 选择器）。
- 实测：
  - requests 直接 GET：返回 2.1KB 的 **“Security Verification”** 空白页（与 `zhaopin_crawler/README.md` 里“连续 requests 第 2 次起被拦”的描述一致）；
  - 无头 Chrome 加载：同样停在 `Security Verification`（“正在验证连接安全性，请勾选下方复选框”），配置选择器 `div.joblist-box__item` **0 命中**。
- 说明：`zhaopin_crawler/`（仓库内独立子项目）用**有头** Playwright + 真实 Edge，并直接读 `window.__INITIAL_STATE__.positionList`，README 声称 2026-10-25 实测可用——这是智联目前更可靠的取数方式。
- 投递：无适配（智联没有“立即沟通”按钮）。
- 判定：**当前不可用**；要修需（a）走真实浏览器通过验证，（b）放弃 CSS，改读 `__INITIAL_STATE__`。

### 4. lagou（拉勾）— ❌ 当前不可用

- 代码路径：有 `api_field_map` + `api_listen_kw=positionAjax.json`，设计上靠旁听。
- 实测：
  - 无头浏览器加载：**“访问验证 / 请按住滑块，拖动到最右边”**，选择器 `li.con_list_item` 0 命中；
  - requests 直接调 `positionAjax.json`：HTTP 200 但返回 11KB 的 **阿里云 WAF 挑战页**（`aliyun_waf_aa`），不是 JSON → `search_via_requests` 会 `r.json()` 抛错。
- 投递：无适配。
- 判定：**当前不可用**；必须登录 + 过滑块后，旁听路径才可能工作；`search_via_requests` 这条路已被 WAF 封死。

### 5. liepin（猎聘）— ❌ 选择器过期

- 代码路径：无 `api_field_map` → Selenium HTML 解析。
- 实测（无登录、无验证码，页面正常加载）：
  - 配置 `item_selector = "div.job-list-item"` → **0 命中**；
  - 实际结构：外层 `div.job-list-box`，卡片是 `div.jobCardPcContainer`（40 个），内部 `jobDetailBox / jobTitleBox / jobCompanyInfoBox`；
  - 实际字段类名示例：标题 `ellipsis-1`、公司 `companyName ellipsis-1`、薪资 `_40108qjbMk`、城市 `ellipsis-1`；
  - 链接形如 `https://www.liepin.com/job/<id>.shtml`。
  - 注意：`_40108...` 这类是构建生成的哈希类名，**不可作为长期选择器**。
- 投递：无适配（猎聘是“申请职位”）。
- 判定：**适配器已过期**；要修建议放弃固定类名，用 `a[href*="/job/"]` + 文本启发式，或改走接口。

### 6. job51（前程无忧）— ❌ 差一个字符，且 API 被 WAF 拦截

- 代码路径：有 `api_field_map` + `api_listen_kw=search-pc`。
- 实测：
  - 配置 `item_selector = "div.joblist_item"`（下划线）→ **0 命中**；实际类名是 `div.joblist-item`（连字符，20 个卡片）；
  - 实际字段类名：岗位名 `jname text-cut`、薪资 `sal text-cut`、公司区 `comp`，容器 `joblist-item-job` / `joblist-item-jobname`；
  - requests 直接调 `api/job/search-pc`：HTTP 200 但返回**同一个阿里云 WAF 页面**，不是 JSON → `search_via_requests` 不可用。
- 投递：无适配。
- 判定：**选择器可低成本修复**（`joblist_item` → `joblist-item`，字段改 `jname/sal` 等），但真实可用性仍取决于登录后能否旁听到接口。

---

## 三、共性问题（比单平台故障更值得修）

1. **城市参数只有 Boss 实现了编码**
   `platforms.city_code()` 只有 `BOSS_CITY_CODES`，其余平台直接返回中文城市名；而智联要 `jl=530`、拉勾要城市码、51job 要 `jobArea=010000`、猎聘要城市码。
   实测后果：猎聘/51job 用 `city=北京` 查出来的是成都、西安、绍兴、湖州的岗位——**城市过滤实际失效**，会污染后续画像与匹配。

2. **投递只有 Boss 一套实现**
   `session.dpage_deliver()` / `dpage_greet()` 里写死了 `a.btn-startchat` 和 `.chat-input textarea`；其它平台详情页是“投递简历/申请职位”，调用会返回“未找到立即沟通按钮”。
   结论：**除 Boss 外，其它平台只能走「半自动」材料包**。

3. **`search_via_requests` 在真实平台基本不可用**
   拉勾、51job 的接口均被 WAF 拦成 HTML；Boss 的 `wapi` 需要浏览器侧的反爬 token。这个函数目前只适合 Mock / 本地接口，README 里说的“不启动浏览器、不被反爬检测”对真实平台不成立。

4. **`platforms.py` 的 HTML `fields` 全部是“最佳起始配置”**
   liepin、job51 已确认过期；智联因验证页无法确认；拉勾被滑块拦截。这符合文件头注释的免责声明，但也意味着**不能把 README 里“多平台检索”当成已实现能力**。

---

## 四、建议的修复顺序（按性价比）

| 优先级 | 动作 | 说明 |
|---|---|---|
| P0 | **Boss 登录实测** | 唯一有投递实现的平台。用你的账号扫码后验证：`joblist.json` 字段、城市码、`a.btn-startchat`、`.chat-input textarea`。把这几项从 `session.py` 抽到 `platforms.py` 的 `delivery` 配置里，避免以后改平台要改代码 |
| P1 | **job51 选择器一行修复** | `div.joblist_item` → `div.joblist-item`；字段换 `jname` / `sal` / `comp`。改完仍需登录验证旁听是否能拿到 `resultbody.job.items` |
| P2 | **智联改走 `__INITIAL_STATE__`** | 复用 `zhaopin_crawler` 已验证的取数方式（有头浏览器 + 服务端渲染 JSON），不要再用 CSS 选择器 |
| P3 | **猎聘重写选择器策略** | 哈希类不可依赖；用链接模式 + 文本位置提取，或走接口 |
| P4 | **补齐城市码表 + 参数校验** | 未识别城市时明确报错/提示，而不是静默返回外地岗位（现在会） |
| P5 | **`search_via_requests` 增加内容类型校验** | 非 JSON（WAF/验证页）时抛“被拦截，请用浏览器路径”，避免 `r.json()` 抛原始异常 |

---

## 五、复现命令（本次检查用的）

```powershell
cd "E:\work\deepseek_workspace\项目相关\job-delivery-system"

# 1) Mock 全链路（检索 + 投递 + 反馈）
.\.venv\Scripts\python.exe mock_e2e.py

# 2) 真实浏览器冒烟（本地 Mock，验证登录/旁听/存 cookie）
.\.venv\Scripts\python.exe verify_browser.py

# 3) 检查某平台配置与实测差异（示例：看有哪些平台配了 API 映射）
.\.venv\Scripts\python.exe -c "import platforms;[print(k, bool(p.get('api_field_map')), p.get('item_selector')) for k,p in platforms.PLATFORMS.items()]"
```

> 本次使用的临时探测脚本（每站 1~2 次请求的无登录探测）已删除，未留在仓库。

---

## 六、最终判断

- **“投递功能对应的爬虫”目前只有 Boss 一条是真的**（Mock 用于测试）：Boss 的检索靠浏览器旁听，投递靠 `btn-startchat` + 聊天框，方向正确，但**没有登录态就无法证明可用**，必须你实测一次。
- 其余 4 家（智联 / 拉勾 / 猎聘 / 前程无忧）在当前代码下**检索跑不通、投递没实现**：`platforms.py` 的选择器是早期写的“起始配置”，至少 liepin、job51 已确认过期；智联、拉勾被验证码/滑块拦在门外。
- 如果目标是“完整走完流程给负责人演示”，**用 Mock 演示 + Boss 真号实测**是当前唯一可靠的组合；其余平台的适配属于“需要按平台重写”的工作量，不是一个 bug 修复能解决。

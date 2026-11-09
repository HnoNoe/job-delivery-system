# 四平台爬虫实测报告

- 日期：2026-11-08
- 环境：Windows 11 / Chrome（有头 + 离屏窗口）/ 新克隆 `main@3aefda7`
- 方法：`requests` 直连 + 浏览器渲染（DrissionPage），并直接调用 `session.dpage_search()` 验证真实返回

## 结论

| 平台 | 可用性 | 实测结果 | 原因 / 处理 |
|---|---|---|---|
| 智联招聘 | ✅ 可用 | 20 条/页，城市=北京 | 旧选择器 `.joblist-box__item` 已失效；新页面为 `www.zhaopin.com/jobs/`，卡片 `div.job-card`；城市参数要用数字码（北京 530）。已修 |
| 猎聘 | ✅ 可用 | 42 条/页，城市=北京 | 搜索结果前端渲染，`requests` 拿不到卡片；新选择器 `div.jobCardPcContainer`；城市参数是 `dqs` 而非 `city`（北京 010）。已修 |
| 前程无忧 | ✅ 可用 | 20 条/页，城市=北京 | 旧选择器 `.joblist_item` 失效，改为 `div.joblist-item`；城市参数用 6 位码（北京 010000）；岗位链接需从 `sensorsdata` 的 `jobId` 拼接。已修 |
| 拉勾 | ❌ 被拦截 | 0 条 | `requests` 与有头浏览器均被滑块验证拦截（“访问验证 / 请按住滑块拖动到最右边”，有 TraceID），需要人工过验证或登录态 |

## 代码改动

- `platforms.py`
  - 智联：`search_url` 改为 `www.zhaopin.com/jobs/`；`item_selector`/`fields` 更新；新增 `ZHILIAN_CITY_CODES`（530/538/763/765）
  - 猎聘：`search_url` 改用 `dqs={city}`；`item_selector`/`fields` 更新；新增 `LIE_PIN_CITY_CODES`（010/020/050020/050090）
  - 前程无忧：`item_selector`/`fields` 更新；新增 `JOB51_CITY_CODES`（010000/020000/030200/040000）
  - `city_code()`：三平台未配置的城市会显式报错，避免静默搜错城市
- `crawler.py`
  - 新增 `parse_job_cards(html, platform_key, base_url)`：解析浏览器渲染后的岗位卡片
  - `_post_job51`：拆「薪资 / 城市 / 状态词」，用 `sensorsdata.jobId` 拼岗位链接
  - `_post_liepin`：去掉链接中的埋点参数，并从卡片文本补薪资
- `session.py`
  - `dpage_search()` 增加 `dom_parse` 分支：先渲染页面，再用 `parse_job_cards()` 解析，不再走 `requests` 兜底

## 验证记录

```
session.dpage_search("zhilian", "后端", "北京", 1)  -> 20 条，城市均为北京
session.dpage_search("liepin",  "后端", "北京", 1)  -> 42 条，城市均为北京
session.dpage_search("job51",   "后端", "北京", 1)  -> 20 条，城市均为北京
session.dpage_search("lagou",   "后端", "北京", 1)  -> 0 条（滑块验证）
```

`run_checks.py`：**All checks passed**（39 用例 + 7 组校验 + Mock 全链路）。

## 城市码覆盖（2026-11-08 补测）

| 平台 | 覆盖城市数 | 数据来源 | 示例（已实测返回对应城市） |
|---|---|---|---|
| 智联招聘 | 18 | 官方筛选接口 `fe-api.zhaopin.com/c/i/search/base/data` 的 `hotCity/allCity` | 杭州 `653` → 20 条杭州岗位 |
| 前程无忧 | 18 | 官方 `dd_city.json` 城市字典 | 杭州 `080200` → 20 条杭州岗位 |
| 猎聘 | 14 | 搜索页筛选面板 `li[data-key=dq]` + 实测 | 郑州 `150020` → 42 条郑州岗位 |
| 拉勾 | — | 直接用城市名，无需编码 | 北京 → `city=北京` |

覆盖城市：北京、上海、广州、深圳、杭州、南京、苏州、成都、武汉、西安、天津、重庆、长沙、郑州、青岛、合肥、厦门、福州（猎聘暂缺长沙/青岛/合肥/厦门/福州，未配置会显式报错）。

## 仍需协助

1. **拉勾**：需要在可见浏览器里手动过一次滑块验证（或先登录），之后我才能复测检索。
2. 智联 / 猎聘 / 前程无忧的 **登录态检索**：应用第③步只检索「已登录」平台，需要先在第②步扫码登录，才能在产品流程里验证；不经登录的 DOM 抓取已证明可用。
3. 本次只测了第 1 页，翻页与「登录后更多结果」尚未覆盖。

# 交接文档 —— 第⑤步「岗位匹配空间」分析工作台

> 范围：2026-11-09 这一轮（新增人物画像、把第⑤步数学分析可视化改造为分析工作台）。
> 仓库：https://github.com/HnoNoe/job-delivery-system
> 本地路径：`E:\work\deepseek_workspace\项目相关\job-delivery-system`
> 基线提交：`913b043`（本轮改动**尚未提交**，见第 8 节）
> 参考原型：`C:\Users\administor\Documents\Codex\2026-11-04\https-github-com-hnonoe-job-delivery\outputs\三版匹配图例-源码与预览.zip`（分析工作台方案）

---

## 0. 一句话现状

第 ⑤ 步现在是**分析工作台**：左三维匹配空间、右岗位详情、顶部人物画像摘要；
同坐标岗位自动聚合、**图上点击点位可选中**、组内岗位可切换、可拖动旋转、可复位视角；
亮/暗/窄屏均可读；原有匹配分、等级、三轴算法、投递/反馈流程与第⑥步统计均未改动。
`run_checks.py`（与 CI 同口径）全绿。

---

## 1. 交付清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `components/match_space/index.html` | **新增** | 工作台前端：原生 HTML/CSS/SVG，无第三方前端依赖；实现正交投影、聚合点、选中态、点击回传、拖动旋转、复位、响应式 |
| `workbench.py` | **新增** | Python 侧适配：组装组件参数（岗位/画像/配色）、声明组件、维护选中态、明细表折叠区 |
| `persona.py` | 新增（上一轮） | 人物画像数据：身份/技能/方向/偏好/一句话/能力匹配/条件契合 |
| `viz.py` | 修改 | 新增 `_fit_point` / `_has_dims` / `_coord_key` / `build_match_space_data` / `resolve_selected_task` / `match_space_rows`；**移除**旧 Plotly `match_space_3d` |
| `theme.py` | 修改 | 新增工作台局部配色 `MATCH_SPACE` / `match_space_colors()`；全站 CSS 改为**亮/暗双主题**（`_theme_tokens` + `_css`），修复暗色页面与组件不一致 |
| `app.py` | 修改 | 第⑤步：KPI + `workbench.render(...)`；撤掉旧数学分析可视化块 |
| `verify_viz.py` | 修改 | 覆盖坐标、聚合、选中回退、未知分数、组件参数、主题切换（28 项 PASS） |
| `verify_health.py` | 修改 | 模块清单加入 `persona`、`workbench`（26 个模块） |
| `portable.spec` | 修改 | 打包时带上 `components/match_space` 与 `persona`/`workbench` |
| `README.md` / `设计文档.md` | 修改 | 更新为分析工作台口径，补充截图路径 |
| `.streamlit/config.toml` | **新增** | 显式主题基线 `base="light"` + 品牌主色，避免自定义 CSS 与原生控件一亮一暗 |
| `start.py` / `portable_launcher.py` | 修改 | 启动时传 `--theme.base light` / `--theme.primaryColor`（便携版读不到项目内 config.toml） |
| `docs/match-space-*.png` | 新增 | 亮色/暗色/窄屏验收截图（合成数据、隔离页面） |
| `docs/sidebar-safe-mode.png` | 新增 | 侧栏「重新开始 + 安全模式开关」截图 |
| `docs/portable-safe-mode.png` | 新增 | 便携版实际运行截图 |
| `docs/button-primary-fixed.png` / `docs/portable-button-fixed.png` | 新增 | 主按钮字体/渐变修复后的源码版与便携版截图 |
| `dist/JobDeliverySystem.exe` | 构建产物（git 忽略） | 单文件便携版，约 139 MB |

---

## 2. 运行与验收

### 2.1 环境（已就绪）

| 项 | 值 |
|---|---|
| 虚拟环境 | `job-delivery-system\.venv`（Python 3.13.5） |
| 依赖 | streamlit 1.66.1 / plotly 7.1.0（⑥ 仍用）/ pandas 3.1.0 |
| 启动 | 双击 `start.bat`，或 `.\.venv\Scripts\python.exe start.py` |
| 地址 | <http://127.0.0.1:8501> |
| 停止 | `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8501 -State Listen).OwningProcess -Force` |

### 2.2 验收路径

1. ① 确认信息 → ② 登录（或 Mock 站）→ ③ 检索 → ④ 准备材料；
2. ⑤ 看到 KPI → 「岗位匹配空间」工作台：
   - 左侧图：普通灰点、聚合点内数字、选中靛蓝点 + 外环 + 虚线投影；
   - 点击任一灰色点位 → 右侧详情立即切换；
   - 详情底部「同坐标岗位」列表可逐一切换；
   - 拖动图旋转；「复位视角」只重置相机；
   - 顶部画像摘要；「完整人物画像」折叠查看偏好/能力匹配；
   - 「查看全部岗位」折叠查看明细表；
3. ⑥ 投递记录、进面试率、画像演进、结果/权重饼图保持原样。

### 2.3 测试

```powershell
cd "E:\work\deepseek_workspace\项目相关\job-delivery-system"
.\.venv\Scripts\python.exe run_checks.py
```

### 2.4 安全模式开关（侧栏）

位置：侧栏「🔄 重新开始」右侧。默认开启（与 `config.SAFE_MODE` 一致）。

- 开启：投递只生成招呼语，不自动发消息（行为与之前一致）；
- 关闭：写入 `config.SAFE_MODE=False`，侧栏出现「⚠️ 安全模式已关闭：投递会真实发送」提示；
  第⑤步的安全模式横幅同步变为“自动投递已开启”；
- 作用域：当前进程；重启后回到 `config.SAFE_MODE` 默认值（默认 True）；
- 已实测：点击关闭 → 警告出现；再点开启 → 警告消失（无头浏览器验证）。

### 2.5 便携版（Windows 单文件）

```powershell
pip install -r requirements-build.txt
$env:PORTABLE_ONEFILE = "1"
.\.venv\Scripts\python.exe -m PyInstaller portable.spec --noconfirm --clean
```

本轮实测（2026-11-09）：

| 项 | 结果 |
|---|---|
| 产物 | `dist\JobDeliverySystem.exe`，139,236,576 字节（2026-11-09 17:33 重建） |
| 依赖自检 | `JobDeliverySystem.exe --check` → exit 0，streamlit/plotly/pandas/DrissionPage 等全部识别 |
| 启动 | `JOBDELIVERY_PORT=8511 .\dist\JobDeliverySystem.exe --no-browser` → HTTP 200 |
| 组件打包 | 运行解压目录 `_MEI*\components\match_space\index.html` 存在（19,609 字节） |
| 页面 | 侧栏含「重新开始 + 安全模式」，亮色主题，见 `docs/portable-safe-mode.png` |
| 登录门控（exe 内实测） | 打开页面 → 「📂 载入上次填写的信息」→ 姓名回填为“张三” → 「✅ 确认信息」→ **「🔍 开始检索」按钮可用**（仅本地登录目录、无 cookie 也放行） |

> 打包时 `tornado` / `nest_asyncio` 报“hidden import not found”（spec 里为旧版 Streamlit 预留），
> 不影响 1.66 的 uvicorn 运行；后续可清理这两项。

### 2.6 按钮字体回退修复（本轮回归）

**现象**：「🔍 开始检索」字体变回原生字体，禁用态是蓝底深灰字，很难看清。

**原因**：给按钮加了 `help=` 后，Streamlit 会把按钮包进 `<span class="stTooltipHoverTarget">`；
原先的 `.stButton > button` 是**直接子代**选择器，包裹层一出现就失配，
自定义按钮样式（SimHei 字体、渐变主按钮、禁用态浅底深字）全部失效，退回原生样式。

**修复**：`theme.py` 五条按钮规则改为后代选择器 `.stButton button`（含 hover / primary / disabled）。

**验证**（源码 + 便携版运行目录）：

| 状态 | 计算结果 |
|---|---|
| 禁用 | `font-family: SimHei, 黑体, …`，文字 `rgb(15,23,42)`（浅底深字） |
| 可用 | 白字，背景 `linear-gradient(120deg, #4F46E5, #7C3AED, #A855F7)` |

截图：`docs/button-primary-fixed.png`、`docs/portable-button-fixed.png`。

**exe 内复测**（17:33 重建版）：

```
portable disabled | font= SimHei, 黑体, "Heiti SC" | color= rgb(15, 23, 42)
portable enabled  | font= SimHei, 黑体, "Heiti SC" | color= rgb(255, 255, 255)
                  | bg= linear-gradient(120deg, #4F46E5, #7C3AED, #A855F7)
```

### 2.7 登录门控与刷新恢复（本轮修复）

| 改动 | 说明 |
|---|---|
| `session.can_search()` | 新增：有 cookie 快照 **或** 本地浏览器登录目录即可进入检索；`is_active()` 仍保留严格 cookie 口径 |
| 第③步门控 | 改用 `can_search`，按钮 `help` 明确显示“未勾选平台 / ①未确认 / ②无可用登录态” |
| 第②步状态 | 区分「🟢 已保存 cookie」「🟡 有本地登录目录，未验证」「⚪ 未登录」 |
| 检索失败提示 | 检索被重定向到登录页时，页面直接警告“登录态已失效，请回第②步重新扫码” |
| `pipeline.latest_user_data()` | 读取最近一次保存的用户（L0/L1/L2/L3） |
| 第①步「📂 载入上次填写的信息」 | 刷新/重开后一键回填表单；不自动确认，仍需人工点确认 |

验证：
- 便携版运行目录（只有 `dprofiles/boss`、无 cookie）→ 门控放行（AppTest：`disabled=False`）；
- 空目录 → 仍禁用；
- 回填按钮实测：`姓名=张三`、`学校=示例大学`，`info_confirmed=False`（需人工确认）；
- 新增 2 个单测：`test_can_search_with_profile_only`、`test_latest_user_data_roundtrip`（共 41 个用例）。


---

## 3. 架构与数据流

```
app.py 第⑤步
  └─ workbench.render(targets, persona_data, key_prefix="ms")
       ├─ viz.build_match_space_data(targets)
       │    → groups[{group_id, coords, task_ids, jobs, count}]
       │      jobs_by_id{task_id: {job, coords, group_id, index}}
       │      default_task_id / job_count / group_count / unknown_task_ids
       ├─ viz.resolve_selected_task(space, session_state 选中ID)   # 失效回退第一个
       ├─ components.declare_component("match_space_workbench", path=components/match_space)
       │    args: jobs / profile / selected / theme
       │    ← 返回 {"task_id": "..."}（点击点位或组内岗位时）
       └─ st.expander("查看全部岗位") + viz.match_space_rows
```

组件通信：`streamlit:componentReady` → `streamlit:render`（args）→ 点击时
`streamlit:setComponentValue({task_id})` → Python 读取返回值写入 `st.session_state`；
组件高度通过 `streamlit:setFrameHeight` 同步。

**数据契约**（`jobs` 单项）：

```json
{"task_id": "12", "name": "Python后端开发工程师", "company": "甲科技",
 "salary": "20-30K", "grade": "A", "score": 0.732,
 "x": 100.0, "y": 100.0, "z": 85.71}
```

坐标 `null` 表示缺少六维分数：不画入图，详情显示“未知”，明细表同样显示“未知”。

---

## 4. 人物画像（`persona.py`）

纯函数，不写库、不改打分：

| 字段 | 说明 |
|---|---|
| 身份 / 姓名 | `学历阶段·学校专业`、L0 姓名 |
| 技能标签 | 先按 L2「技术工具」出现顺序，再补关键词命中 |
| 求职方向 / 偏好 | L3 意向岗位；城市/行业/薪资/到岗 |
| 能力匹配 | 技能、方向两个维度的平均达成率（%） |
| 条件契合 | 学历/薪资/行业/城市四维平均达成率（%） |
| 画像规模 | 经历数 + 权重是否已被反馈修正 |

第⑤步只把姓名、身份/方向、3–5 个技能放进摘要条；其余收进「完整人物画像」折叠区。

---

## 5. 三维空间与聚合

### 5.1 坐标（保持不变）

```
X = clip(技能匹配得分 / 40 × 100, 0, 100)
Y = clip(岗位方向得分 / 25 × 100, 0, 100)
Z = clip((学历 + 薪资 + 行业 + 城市) / 35 × 100, 0, 100)
```

条件四项**先求和再截断**，不是逐项清零；未知分数不参与计算。

### 5.2 聚合

- 用未取整坐标，按 6 位小数归一键合并；不做抖动、不按显示整数合并；
- 组内顺序沿用 `targets` 原顺序；`task_id` 集合与聚合前完全一致；
- 单岗位点不显示数字；组点内数字为岗位数量。

### 5.3 视觉

- 普通点 `#9BA6BC`（暗色 `#8693AE`）、统一 11px；选中点 `#5854DC`（暗色 `#AAA4FF`）19px + 外环；
- 选中时画虚线投影到 X/Y 平面；网格 `#D7DCE8`/`#485367`，主刻度只有 0/50/100；
- 参考角标注 `100 / 100 / 100`，不是真实岗位；
- 颜色只表达普通/选中，A/B/C 只在详情文字徽标；点大小不编码匹配分；
- 工作台配色见 `theme.MATCH_SPACE`（亮/暗两套），不污染全站等级色。

---

## 6. 交互实现与验证

| 能力 | 状态 | 说明 |
|---|---|---|
| 图中点击点位 → 详情 | ✅ 已实现 | 组件内按钮层 + `setComponentValue` 回传 |
| 同坐标岗位切换 | ✅ | 详情底部列表按钮 |
| 键盘访问 | ✅ | 点位、组内岗位均为原生 `<button>`，可 Tab/Enter |
| 拖动旋转 | ✅ | Pointer 事件，限制角度范围 |
| 页面重跑保持相机 | ✅ | 相机状态保存在组件 JS 内；选中由 Python 传回 |
| 复位视角 | ✅ | 只重置 `cam.a/e`，不改选中 |
| 新结果旧 ID 失效 | ✅ | `resolve_selected_task` 回退第一个岗位；组件内也做兜底 |
| 空数据/缺字段 | ✅ | 空态提示；未知分数不画点、详情显示“未知” |
| 暗/亮主题 | ✅ | Python 传入配色变量，组件与页面同主题 |

**点击回传实测**（DrissionPage 无头浏览器，2026-11-09）：

```
frames: 1（/component/workbench.match_space_workbench/index.html）
marks: 8
title before: Python后端开发工程师
点击第 3 个组点（数据开发组）
title after: 数据开发工程师
Python 侧 session_state 选中ID: 5   # 组件值已回传
```

> 结论：不再需要“降级为仅选择器联动”。`Scatter3d` 原生点选确实不支持，
> 因此改为轻量自定义组件，点击链路完整。

---

## 7. 测试与验证

```powershell
.\.venv\Scripts\python.exe run_checks.py     # All checks passed.
```

| 项 | 结果 |
|---|---|
| `tests/`（unittest，41 用例） | 通过 |
| `verify_formulas.py` | exit 0 |
| `verify_resume_parse.py` | exit 0 |
| `verify_rematch.py` | exit 0 |
| `verify_ui_compat.py` | exit 0 |
| `verify_viz.py` | exit 0（**28 项 PASS**） |
| `verify_health.py` | exit 0（26 个模块导入成功） |
| `mock_e2e.py` | 通过 |
| AppTest 跑完整 `app.py`（灌入④结果） | 无异常，1 个自定义组件、明细表正常 |

浏览器视觉检查（合成数据、隔离页面）：

| 场景 | 文件 |
|---|---|
| 亮色桌面 | `docs/match-space-light.png` |
| 暗色桌面 | `docs/match-space-dark.png` |
| 窄屏（480px） | `docs/match-space-narrow.png` |

另：20 个岗位的预览页验证了聚合、选中、详情联动与无满屏编号。

---

## 8. 未提交改动与提交建议

```
 M README.md
 M app.py
 M loop.py
 M pipeline.py
 M portable.spec
 M portable_launcher.py
 M session.py
 M start.py
 M tests/test_regressions.py
 M theme.py
 M verify_health.py
 M verify_viz.py
 M viz.py
 M 设计文档.md
?? .streamlit/config.toml
?? persona.py
?? workbench.py
?? components/match_space/index.html
?? docs/match-space-light.png
?? docs/match-space-dark.png
?? docs/match-space-narrow.png
?? docs/sidebar-safe-mode.png
?? docs/portable-safe-mode.png
?? HANDOFF-人物画像与三维匹配空间.md
```

建议：

```powershell
git add persona.py workbench.py components docs .streamlit \
        app.py viz.py theme.py session.py loop.py pipeline.py \
        start.py portable_launcher.py portable.spec tests \
        verify_viz.py verify_health.py README.md 设计文档.md \
        HANDOFF-人物画像与三维匹配空间.md
git commit -m "feat(ui): 第⑤步分析工作台；安全模式开关；登录门控与刷新回填；便携版打包"
```

提交前再跑一次 `run_checks.py`。

---

## 9. 已知限制

1. **依赖组件目录**：`components/match_space/index.html` 必须随源码/打包一起分发；
   缺失时工作台只显示警告，不阻塞其他步骤。便携版已在 `portable.spec` 加 datas，但本轮**未实际重建便携包**验证。
2. **相机状态在 iframe 内**：普通页面重跑保持；若 Streamlit 因布局变化重建组件实例，相机会回到默认角度（选中状态仍保留）。
3. **没有全局搜索框**：键盘可经“点位按钮 → 组内岗位按钮”到达所有岗位；
   「查看全部岗位」表格只读，不提供跳转。
4. **无 Plotly 3D 回退**：`viz.match_space_3d` 已移除；若组件加载失败没有降级图。
5. **未知坐标**不画点（不会伪造位置），只出现在明细表与详情文字中。
6. **20+ 岗位**已验证不显示编号、不拥挤；极端数量（上百）未做性能测试。
7. 组件高度用 `setFrameHeight` + `ResizeObserver` + 1.5s 兜底轮询；若网络/渲染极慢，首次可能短暂留白。
8. `theme` 全站 CSS 已改为亮/暗双令牌，但个别旧组件（岗位卡片等）沿用等级色，暗色下如需进一步统一可再调。
9. **测试不覆盖 JS**：组件点击链路由无头浏览器人工脚本验证，未纳入 `run_checks.py`
   （CI 无浏览器依赖）。若后续要长期保障，可加 Playwright 端到端用例。
10. **主题基线被显式固定**：`.streamlit/config.toml` 设 `base="light"`，避免自定义 CSS 与原生控件
   一亮一暗；需要暗色时用 `start.py --theme.base dark` 或便携版 `--theme.base=dark` 启动。
   这条也意味着“跟随系统暗色”不再自动生效。
11. **便携版验证范围**：已实测 exe 启动、①回填→确认→③按钮可用、侧栏开关、组件文件随包解压；
    但便携进程内没有实际完成 ③检索→④材料→⑤工作台，建议交付前手动走一遍完整流程。
12. **exe 未签名**：139 MB 单文件，首次运行可能触发 SmartScreen；分发给他人时需说明来源。

---

## 10. 后续 TODO

1. 给组件加一条可选的全局岗位搜索/跳转（键盘用户更省 Tab）；
2. 用 Playwright 把“点击→详情→回传”固化为 CI 用例；
3. 若需要对比视图，可复用原型中的“对比清单”方案（当前未实现）；
4. 聚类/选轴（负责人方向）：可在 `build_match_space_data` 之外增加坐标模式，
   保持当前三轴为默认口径；
5. 便携版重建后验证 `components/` 是否正确进入 `_MEIPASS`。

---

## 11. 排障 FAQ

| 现象 | 处理 |
|---|---|
| 第⑤步只显示“匹配空间组件缺失” | 确认 `components/match_space/index.html` 存在；便携版需重新打包 |
| 组件区域空白/高度不对 | 刷新页面；看浏览器控制台是否有组件 iframe 报错；`workbench.py` 用 `declare_component(path=...)` |
| 点击不出详情 | 确认点击的是圆点/岗位按钮；组件值回传依赖 Streamlit 组件协议，勿用 `st.markdown` 嵌 HTML 替代 |
| 暗色下卡片与页面不一致 | 检查 `--theme.base` 或 Streamlit 主题设置；`theme.is_dark()` 优先读配置，其次 `st.context.theme` |
| 8501 打不开 | 看 `logs\streamlit.err.log`；用 `127.0.0.1` 而非 `localhost` |

---

## 12. 相关文档

| 文档 | 内容 |
|---|---|
| `README.md` | 功能总览与分析工作台说明 |
| `设计文档.md` | 六层架构、五公式、可视化口径 |
| `HANDOFF.md` | 上游历史交接（截至 2026-10-12） |
| `C:\...\outputs\交给DS-三维匹配图改造实施说明.md` | 本轮任务说明（需求来源） |
| `C:\...\outputs\三版匹配图例-源码与预览.zip` | 视觉/交互原型（分析工作台方案） |
| 上级目录 `job-delivery-system-本地接手分析.md` | 环境基线、漏洞清单、AI 训练切入点 |
| 上级目录 `job-delivery-system-运行流程说明.md` | 六步流程逐段调用链 |

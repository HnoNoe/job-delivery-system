# 项目交接 Prompt（给下一个会话的完整上下文）

> 项目：面向大学毕业生的求职批量投递系统（Job Batch Delivery System）
> 路径：`C:/Users/Camevian/AppData/Local/Cline/job-delivery-system`
> 依据：专利技术交底书《一种主要面向大学毕业生的求职批量投递系统及方法》

---

## 一、项目背景与定位

把"求职批量投递"抽象为**顺序化、可核验的数据处理方法**，不是简单的"自动发简历工具"。专利五大目标：

1. 多来源岗位信息**统一字段**处理；
2. 目标岗位 ↔ 针对性简历 ↔ 投递入口 ↔ 投递状态 **任务级关联**；
3. 生成式 AI 输出受**字段表约束 + 短任务切分 + 核对回写**（系统性抑制幻觉）；
4. 投递结果**集中回写**；
5. 画像依据反馈做**数学可验证的动态修正**。

六层架构：①用户输入层 → ②模型层1画像 → ③操作层1匹配 → ④操作层2建任务 → ⑤模型层2执行 → ⑥结果输出层，底层是「统一字段数据库」（字段名全局唯一 + 字段值可核对）。

---

## 二、五个核心数学公式（都在 formulas.py，有回归测试）

- **式一** 用户表示 `u = Σ α_k·v_k`（凸组合，α≥0 和为1）
- **式二** 余弦相似 `s = (u·j)/(‖u‖‖j‖)`
- **式三** 匹配分 `p = σ(w_s·s + w_δ·δ)`，`δ = cos(j,c_+)−cos(j,c_-)`（间隔特征，冷启动时 δ=0）
- **式四** 该岗经历分配 `γ_k = α_k·e^{τ·b_k} / Σ α_m·e^{τ·b_m}`（指数倾斜）
- **式五** 回写 `α_k ← α_k·e^{η·z·I_k}` 再归一化（乘性更新，z=进面试与否，I_k=是否写入该岗简历）

七步流程 + 第八步「再画像再匹配」闭环（`pipeline.re_match`，式三 δ 从 0 → 生效）。

---

## 三、当前已完成功能（系统可完整运行）

1. **简历解析**（recommend.py `resume_parse` + `_parse_experiences`）：L0 全字段（姓名/性别/民族/政治面貌/现居/籍贯/出生/GPA/专业排名/学院/入学毕业/学历阶段）+ L2 经历多类型（实习/项目/竞赛/论文/专利/学生工作，按时间范围切分 + 量化成果提取 + 角色识别）。
2. **批量投递**（delivery.py `deliver_batch`）：Boss 直聘「立即沟通」通道，三重防封护栏（每日上限 20 / 单次批次 5 / 间隔 8 秒）+ 风控熔断；安全模式 `SAFE_MODE=True` 默认拒绝真投。
3. **Mock 测试站**（mock_site.py）：高保真复现 Boss 直聘关键结构（`/wapi/zpgeek/search/joblist.json` 搜索接口、`/job_detail/<id>.html` 详情页 `a.btn-startchat`、`.chat-input textarea` 聊天框、`/wapi/zpgeek/friend/add.json` 发招呼语、`/api/greets` 投递记录），零依赖标准库。
4. **数学可视化**（app.py 第⑤⑥步，**全部用 Plotly 交互式**，网页内美观显示，非 PNG）：
   - 岗位等级分布环形图、匹配分横向柱状图、六维适配雷达图、六维得分分组柱状图、所有岗位六维堆叠柱状图、技能覆盖柱状图、投递转化漏斗图、PCA 语义散点图、匹配分进化对比图、投递结果/经历权重环形图。
5. **画像适配分析**：六维（技能40+方向25+学历15+薪资10+行业5+城市5）雷达图 + 堆叠柱状图 + PCA 语义空间散点图。
6. **学习笔记**：`notes/学习笔记-专利核心思想.md`（专利核心思想 + 数学细节推导 + 可视化设计思路）。

---

## 四、关键文件清单

| 文件 | 作用 |
|---|---|
| `app.py` | Web Dashboard（6 步向导，Streamlit + Plotly） |
| `config.py` | 全局配置（超参数、SAFE_MODE、防封参数、SMTP） |
| `schema.py` | 统一字段 schema（L0/L1/L2/L3/JOB/TASK 字段白名单） |
| `formulas.py` | 五个公式（式一~式五） |
| `recommend.py` | 匹配分析/等级/推荐理由/画像摘要/招呼语/简历解析 |
| `verification.py` / `profile.py` / `matching.py` / `tasks.py` | 步骤一~四 |
| `generation.py` / `delivery.py` / `feedback.py` | 步骤五~七 |
| `pipeline.py` / `loop.py` | 流程编排 |
| `crawler.py` / `platforms.py` / `session.py` / `form_filler.py` | 采集/平台注册/会话/表单投递 |
| `mock_site.py` / `mock_e2e.py` | Mock 测试站 + 全量端到端测试 |
| `verify_*.py` | 5 个回归测试 |
| `README.md` / `设计文档.md` / `notes/学习笔记-专利核心思想.md` | 文档 |

---

## 五、运行与测试命令

```bash
cd C:/Users/Camevian/AppData/Local/Cline/job-delivery-system

# 启动 Web 面板
python start.py            # 或 start.bat，自动打开浏览器 http://localhost:8501

# Mock 站（全量功能联调，不碰真实平台）
python mock_site.py        # 启动本地 mock 站 http://127.0.0.1:5001
python mock_e2e.py         # 全量端到端：检索→画像→匹配→生成简历→投递→反馈→画像演进

# 回归测试（离线、不联网、不启动浏览器）
python verify_formulas.py      # 式一~式五数学自洽性
python verify_resume_parse.py  # 简历解析
python verify_viz.py           # 可视化数据源
python verify_rematch.py       # 画像闭环再匹配（式三 δ）
python verify_ui_compat.py     # 前端渲染兼容性

# CLI
python main.py batch [--limit N]   # 批量投递
python main.py search <平台> <关键词>
```

---

## 六、待办 / 下一步方向

1. **实测真实 Boss 直聘**：选择器（`a.btn-startchat`、`.chat-input textarea`）和接口可能随平台改版变化，接真实平台需实测扫码验证并微调。
2. **投递质量评估**：进面试率、平均匹配分等指标（可加在第⑥步）。
3. **可视化微调**：Plotly 配色/布局可进一步打磨（当前用 #4f46e5 主题色）。
4. **更多平台适配**：mock 站可扩展 zhilian/lagou/job51 的接口结构。
5. **可视化数据准备抽函数**：app.py 第⑤步可视化逻辑较长，可抽到 recommend.py 供复用+测试。

---

## 七、重要注意事项（务必遵守）

1. **专利 docx 附件已失效**（原附件路径不存在），专利核心内容已沉淀在 `设计文档.md` 和 `notes/学习笔记-专利核心思想.md`。不要再去爬/找原始 docx。
2. **用户明确拒绝过"爬整个 Boss 直聘"**——这是合法边界，全站爬取违反平台协议 + 《反不正当竞争法》+ 有真实诉讼先例。只能做：登录态少量岗位检索、mock 站本地测试。
3. **用户要的是网页里美观显示（Plotly 交互式图表），不要 PNG 文件**。之前出 PNG 被用户纠正过。
4. **SAFE_MODE 默认开启**，投递不会真正发消息给 HR；改 `config.SAFE_MODE=False` 才真投（有封号风险，风险自负）。
5. 字段名全局唯一 + 字段值可核对是专利灵魂，改动 schema 时要保证这两个属性不被破坏。
6. 每个数学对象落在已知集合上（权重在概率单纯形、分数在 (0,1)），这是回归测试 verify_formulas.py 验证的，改动公式时先跑它。

---

## 八、当前环境状态

- 系统时间约 21:00（用户此前要求"监测电脑时间到 9:00 停止"）。
- Streamlit 服务运行于 `http://localhost:8501`（HTTP 200）。
- 数据目录 `data/` 已清理（仅保留空库 jobdelivery.db）。
- 所有回归测试通过（退出码 0）。

---

## 九、2026-10-09 设计系统升级（本轮新增）

1. **新增 `theme.py` 设计系统**：色彩令牌（PRIMARY #4F46E5 / 等级语义色 / 中性色阶）、
   全站 CSS 主题（hero 横幅、步骤圆章标题、按钮渐变、卡片化折叠面板、侧栏状态圆牌、
   指标卡）、Plotly 统一模板 `jd`（字体/色板/网格/hover/图例）。
2. **`theme.chart(fig)` 是图表唯一渲染入口**：内部做 `width='stretch'` 跨版本适配，
   app.py 不再有裸 `use_container_width=` —— 顺带修复了 verify_ui_compat.py 的静态检查
   （交接时该测试实际是 FAIL 的，命中 11 处弃用调用，现已全 PASS）。
3. app.py 呈现层全部改走 theme 常量，业务逻辑零改动；第⑤步新增 KPI 指标卡
   （目标岗位/平均匹配分/A级数/已投递），第⑥步统计改为指标卡。
4. 预览验证产物：`_design_preview.py`（一键起服+无头截图）、
   `preview_landing.png`（落地页）、`preview_charts.png/.html`（图表模板效果）。
   注意：DrissionPage 无头截图需 `co.auto_port()`，否则与用户已开 Chrome 端口冲突（404）。
5. 运行环境：用户 Python `C:\Users\Camevian\AppData\Local\Programs\Python\Python313\python.exe`
   （streamlit 1.52.2 / plotly 6.5.2）。项目已复制到
   `C:/Users/Camevian/Documents/Kimi/Workspaces/智投链/job-delivery-system`，
   后续在此副本上维护；原 Cline 目录不再改动。

---

## 十、2026-10-09 交互逻辑与健康度升级（第二轮）

1. **修复「重新开始」静默失效**：原代码先 `st.rerun()` 再清平台会话，
   rerun 会中断执行导致清理永远跑不到。已改为先清会话/浏览器、再清界面状态、最后单次 rerun。
2. **步骤状态感知**：新增 `_wizard_states()` 从界面状态+数据库推导六步完成度；
   侧栏有六步进度条（theme.stepper），每步标题右侧挂状态圆牌（✓已完成/●进行中/○待开始）。
3. **按钮前置门控**：③检索、④准备材料 在条件不满足时直接禁用并显示 🔒 引导文案，
   不再"点了才警告"。
4. **空态引导**：③⑤⑥ 无数据时显示 theme.empty_state 虚线卡片，说明这一步要做什么。
5. **步骤① 表单分组**：基本信息/教育信息/求职意向三段标题。
   注意：Streamlit 分列容器先于穿插的 markdown 渲染，分组标题必须各配一组 columns。
6. **封装修复**：外部模块不再直接读 `session._DPAGES` 私有变量，
   统一走新的公共访问器 `session.is_active(pk)`。
7. **新增 verify_health.py**（第 6 个回归测试）：schema 无重复字段、config 超参数合法域、
   23 个模块可干净导入、app.py 无 rerun 后不可达代码、无弃用 API 调用（theme.py 豁免）、
   数据库核心表齐全。当前 6/6 全部通过。

---

## 十一、2026-10-12 全量设计升级（第三轮）

1. **新增 `viz.py` 可视化层**：app.py 里 200+ 行图表构造全部抽走
   （grade_donut / score_bar / six_dim_radar / six_dim_bars / stacked_dims /
   skill_coverage / delivery_funnel / pca_scatter / evolution_bar / result_pie / weight_pie），
   app.py 只做布局；`_design_preview.py` 与 app.py 同源调用 viz，预览即真实效果。
2. **岗位卡片重设计**：theme.job_card_header（等级徽章 + 薪资/等级分元信息 +
   匹配分彩色进度条），替换原 emoji+文字两行。
3. **投递质量指标**：feedback.get_quality()（进面试率=进面试÷已标注、
   反馈率=已标注÷已投递、已投递平均匹配分），第⑥步升级为 5 指标卡。
4. **mock_site.py 界面打磨**：统一 _STYLE（卡片列表、Boss 风青色按钮、橙色薪资），
   所有 DOM 类名/选择器原样保留，mock_e2e 照常通过。
5. **清理**：app.py 移除不再使用的 matplotlib / plotly 直接导入（图表全在 viz.py）。
6. theme.chart 统一清空 px 默认的 "variable" 图例标题。
7. 回归：6 个 verify_* + mock_e2e 全部通过。

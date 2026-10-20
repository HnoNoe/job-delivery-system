"""设计系统：全站统一的视觉令牌、CSS 主题与 Plotly 图表模板。

设计师视角的三层抽象：
1. 色彩 / 字体 / 间距令牌（PALETTE / FONT_STACK）
2. Streamlit 组件级 CSS 覆盖（CSS，hero、步骤头、按钮、卡片、侧栏）
3. Plotly 统一模板（register_template + chart() 渲染入口，
   同时承接 use_container_width 的跨版本适配，替代散落的旧写法）

业务代码只需 from theme import ...，不要在 app.py 里写裸颜色值。
"""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------- 色彩令牌
INK = "#0F172A"          # 主文字
SLATE = "#475569"        # 次文字
MUTED = "#94A3B8"        # 弱化文字 / 次要系列
LINE = "#E2E8F0"         # 分隔线 / 网格
PAPER = "#F7F8FC"        # 页面底色
CARD = "#FFFFFF"         # 卡片底色

PRIMARY = "#4F46E5"      # 品牌主色（靛蓝）
VIOLET = "#7C3AED"
PURPLE = "#A855F7"
INFO = "#0EA5E9"
SUCCESS = "#10B981"      # A 级 / 正向
WARNING = "#F59E0B"      # B 级 / 关注
DANGER = "#EF4444"       # C 级 / 负向
ROSE = "#F43F5E"
TRACK = "#C7D2FE"      # 满分/基准轨道（主色的浅阶）

# 等级语义色（A=强匹配绿 / B=机会琥珀 / C=不推荐红）
GRADE = {"A": SUCCESS, "B": WARNING, "C": DANGER,
         "A级": SUCCESS, "B级": WARNING, "C级": DANGER}

# 图表分类色板（主色起、环绕展开，避免相邻色相打架）
CHART_SEQ = [PRIMARY, VIOLET, INFO, SUCCESS, WARNING, ROSE, "#14B8A6", "#8B5CF6"]

# 反馈前后对比（前=灰、后=主色，视线自然落到“后”）
EVOLUTION = {"反馈前": MUTED, "反馈后": PRIMARY}

FONT_STACK = ('"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", '
              '"Source Han Sans SC", system-ui, sans-serif')

GRADIENT = f"linear-gradient(120deg, {PRIMARY} 0%, {VIOLET} 55%, {PURPLE} 100%)"


# ---------------------------------------------------------------- Plotly 模板
def register_template():
    """注册并启用全站统一的 Plotly 模板（幂等，可重复调用）。"""
    tpl = go.layout.Template(
        layout=dict(
            font=dict(family=FONT_STACK, size=13, color=SLATE),
            colorway=CHART_SEQ,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=16, r=16, t=52, b=16),
            title=dict(font=dict(size=15, color=INK, family=FONT_STACK), x=0.02, xanchor="left"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1.0, xanchor="right",
                        font=dict(size=12), bgcolor="rgba(0,0,0,0)",
                        title=dict(text="")),
            hoverlabel=dict(bgcolor=CARD, bordercolor=LINE,
                            font=dict(family=FONT_STACK, size=12, color=INK)),
            xaxis=dict(gridcolor="rgba(0,0,0,0)", linecolor=LINE, tickfont=dict(size=12),
                       zerolinecolor=LINE),
            yaxis=dict(gridcolor=LINE, linecolor="rgba(0,0,0,0)", tickfont=dict(size=12),
                       zerolinecolor=LINE),
            bargap=0.28,
        )
    )
    pio.templates["jd"] = tpl
    pio.templates.default = "jd"


register_template()


def chart(fig, height=None, **kwargs):
    """统一的图表渲染入口：应用高度，并按 Streamlit 版本选择全宽参数。

    Streamlit ≥1.49 弃用 use_container_width（关键字实参在静态检查中被禁），
    因此集中在这里做版本自适应；业务代码一律走本函数。
    """
    if height:
        fig.update_layout(height=height)
    # px 长表图默认带 "variable" 图例标题，本项目不设置有意义的图例标题，统一清空
    fig.update_layout(legend_title_text="")
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        if (major, minor) >= (1, 49):
            return st.plotly_chart(fig, width="stretch", **kwargs)
    except Exception:
        pass
    return st.plotly_chart(fig, use_container_width=True, **kwargs)


# ---------------------------------------------------------------- 页面构件
def hero():
    """顶部品牌横幅。"""
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-inner">
            <div class="hero-title">🎯 求职批量投递系统</div>
            <div class="hero-sub">真实检索 · 智能匹配（A/B/C 等级 + 推荐理由 + 分数明细） ·
                个性化简历与招呼语 · 画像随反馈闭环进化</div>
            <div class="hero-tags">
              <span>六层架构</span><span>五个数学公式</span><span>统一字段库</span><span>画像闭环</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(no, title, caption="", status=None):
    """步骤标题：编号圆章 + 标题 + 说明 + 状态圆牌。

    status ∈ done（已完成）/ active（进行中）/ todo（待开始），None 不显示。
    """
    cap = f'<div class="sec-cap">{caption}</div>' if caption else ""
    _STATUS = {"done": ("ok", "✓ 已完成"), "active": ("warn", "● 进行中"),
               "todo": ("off", "○ 待开始")}
    badge = (f'<div class="sec-status">{pill(*_STATUS[status])}</div>'
             if status in _STATUS else "")
    st.markdown(
        f"""
        <div class="sec">
          <div class="sec-num">{no}</div>
          <div class="sec-head"><div class="sec-title">{title}</div>{cap}</div>
          {badge}
        </div>
        """,
        unsafe_allow_html=True,
    )


def pill(kind, text):
    """状态小圆牌。kind ∈ ok / off / warn。"""
    return f'<span class="pill pill-{kind}">{text}</span>'


def stepper(steps):
    """侧栏六步进度条。steps = [(编号+名称, state), ...]，state ∈ done/active/todo。"""
    cells = []
    for label, state in steps:
        icon = {"done": "✓", "active": "●", "todo": "○"}.get(state, "○")
        cells.append(f'<div class="stp stp-{state}"><span class="stp-ic">{icon}</span>{label}</div>')
    done_n = sum(1 for _, s in steps if s == "done")
    pct = round(100 * done_n / len(steps)) if steps else 0
    st.markdown(
        f"""
        <div class="stepper">
          <div class="stepper-bar"><div class="stepper-fill" style="width:{pct}%"></div></div>
          <div class="stepper-row">{"".join(cells)}</div>
          <div class="stepper-pct">进度 {done_n}/{len(steps)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(icon, title, desc=""):
    """空态引导卡片：图标 + 标题 + 说明。"""
    d = f'<div class="empty-desc">{desc}</div>' if desc else ""
    st.markdown(
        f"""
        <div class="empty">
          <div class="empty-icon">{icon}</div>
          <div class="empty-title">{title}</div>{d}
        </div>
        """,
        unsafe_allow_html=True,
    )


def job_card_header(job):
    """岗位卡片头：等级徽章 + 岗位/单位 + 薪资与等级分 + 匹配分进度条。"""
    grade = job.get("等级", "")
    color = GRADE.get(grade, MUTED)
    try:
        p = float(job.get("score") or 0)
    except (TypeError, ValueError):
        p = 0.0
    pct = max(0, min(100, round(p * 100)))
    return (
        f'<div class="jcard">'
        f'<div class="jcard-top">'
        f'<span class="jgrade" style="color:{color};background:{color}1A;'
        f'border:1px solid {color}55">{grade} 级</span>'
        f'<span class="jtitle">{job.get("岗位名称", "")}</span>'
        f'<span class="junit">{job.get("单位名称", "")}</span>'
        f'</div>'
        f'<div class="jmeta">💰 {job.get("薪资", "—")} · '
        f'等级分 {job.get("等级分", "—")}/100 · 匹配分 {p:.3f}</div>'
        f'<div class="jbar"><div class="jbar-fill" '
        f'style="width:{pct}%;background:{color}"></div></div>'
        f'</div>'
    )


# ---------------------------------------------------------------- CSS 主题
CSS = f"""
<style>
/* ===== 基础版面 ===== */
.stApp {{ background: {PAPER}; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1160px; }}
html, body, [class*="css"] {{ font-family: {FONT_STACK}; }}
h1, h2, h3, h4 {{ color: {INK}; letter-spacing: .01em; }}
p, li, .stMarkdown {{ color: {SLATE}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {MUTED} !important; }}
hr {{ border: none; border-top: 1px solid {LINE}; margin: 1.6rem 0 .6rem; }}

/* ===== 顶部品牌横幅 ===== */
.hero {{
  position: relative; overflow: hidden;
  background: {GRADIENT};
  border-radius: 18px; padding: 1.9rem 2.2rem 1.6rem; margin-bottom: 1.2rem;
  box-shadow: 0 12px 32px -12px rgba(79, 70, 229, .45);
}}
.hero::before {{
  content: ""; position: absolute; inset: 0;
  background:
    radial-gradient(420px 200px at 88% -30%, rgba(255,255,255,.28), transparent 60%),
    radial-gradient(300px 160px at 6% 120%, rgba(255,255,255,.14), transparent 60%);
}}
.hero-inner {{ position: relative; }}
.hero-title {{ color: #fff; font-size: 1.75rem; font-weight: 800; letter-spacing: .02em; }}
.hero-sub {{ color: rgba(255,255,255,.88); margin-top: .45rem; font-size: .95rem; }}
.hero-tags {{ margin-top: .9rem; display: flex; gap: .5rem; flex-wrap: wrap; }}
.hero-tags span {{
  color: #fff; font-size: .75rem; padding: .18rem .7rem; border-radius: 999px;
  background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
  backdrop-filter: blur(4px);
}}

/* ===== 步骤标题 ===== */
.sec {{ display: flex; align-items: center; gap: .8rem; margin: .4rem 0 .7rem; }}
.sec-num {{
  width: 2.1rem; height: 2.1rem; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 1rem;
  background: {GRADIENT};
  box-shadow: 0 4px 12px -4px rgba(124, 58, 237, .55);
}}
.sec-title {{ font-size: 1.18rem; font-weight: 700; color: {INK}; }}
.sec-cap {{ font-size: .83rem; color: {MUTED}; margin-top: .1rem; }}

/* ===== 状态小圆牌 ===== */
.pill {{
  display: inline-flex; align-items: center; gap: .3rem;
  font-size: .78rem; font-weight: 600; padding: .12rem .6rem; border-radius: 999px;
}}
.pill-ok   {{ color: #047857; background: #D1FAE5; }}
.pill-off  {{ color: {SLATE};  background: #E2E8F0; }}
.pill-warn {{ color: #B45309; background: #FEF3C7; }}

/* ===== 按钮 ===== */
.stButton > button {{
  border-radius: 10px; font-weight: 600; border: 1px solid {LINE};
  transition: transform .08s ease, box-shadow .15s ease;
}}
.stButton > button:hover {{
  transform: translateY(-1px);
  box-shadow: 0 6px 16px -8px rgba(15, 23, 42, .35);
}}
.stButton > button[kind="primary"] {{
  background: {GRADIENT}; border: none;
  box-shadow: 0 8px 20px -8px rgba(79, 70, 229, .6);
}}
.stButton > button:disabled {{ opacity: .45; transform: none; box-shadow: none; }}

/* ===== 输入控件 ===== */
.stTextInput input, .stNumberInput input, .stTextArea textarea {{
  border-radius: 10px; border-color: {LINE};
}}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{
  border-color: {PRIMARY}; box-shadow: 0 0 0 3px rgba(79, 70, 229, .15);
}}

/* ===== 折叠卡片 ===== */
[data-testid="stExpander"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 14px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, .05);
  overflow: hidden;
}}
[data-testid="stExpander"] details summary {{
  padding: .7rem 1rem; font-weight: 600; color: {INK};
}}
[data-testid="stExpander"] details summary:hover {{ color: {PRIMARY}; }}

/* ===== 数据表 / 代码块 ===== */
[data-testid="stDataFrame"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .35rem;
}}
.stCode, [data-testid="stCodeBlock"] {{ border-radius: 10px; }}

/* ===== 指标卡 ===== */
[data-testid="stMetric"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 14px;
  padding: .9rem 1.1rem; box-shadow: 0 1px 3px rgba(15, 23, 42, .05);
}}
[data-testid="stMetricLabel"] {{ color: {MUTED}; font-weight: 600; }}
[data-testid="stMetricValue"] {{ color: {INK}; font-weight: 800; }}

/* ===== 提示条圆角统一 ===== */
[data-testid="stAlert"] {{ border-radius: 12px; }}

/* ===== 侧栏 ===== */
[data-testid="stSidebar"] {{
  background: #FBFBFE; border-right: 1px solid {LINE};
}}
[data-testid="stSidebar"] .stCaption {{ letter-spacing: .02em; }}

/* ===== Plotly 图表容器留呼吸感 ===== */
[data-testid="stPlotlyChart"] {{ margin-bottom: .4rem; }}

/* ===== 步骤标题状态 ===== */
.sec-head {{ flex: 1; }}
.sec-status {{ margin-left: auto; flex: none; }}

/* ===== 侧栏六步进度条 ===== */
.stepper {{ margin: .3rem 0 .4rem; }}
.stepper-bar {{
  height: 6px; border-radius: 999px; background: {LINE}; overflow: hidden;
}}
.stepper-fill {{
  height: 100%; border-radius: 999px; background: {GRADIENT};
  transition: width .4s ease;
}}
.stepper-row {{
  display: grid; grid-template-columns: repeat(3, 1fr); gap: .3rem; margin-top: .5rem;
}}
.stp {{
  font-size: .72rem; color: {MUTED}; display: flex; align-items: center; gap: .25rem;
  white-space: nowrap;
}}
.stp-ic {{ font-weight: 700; }}
.stp-done {{ color: #047857; }}
.stp-active {{ color: {PRIMARY}; font-weight: 700; }}
.stepper-pct {{ font-size: .72rem; color: {MUTED}; margin-top: .35rem; text-align: right; }}

/* ===== 空态引导卡片 ===== */
.empty {{
  background: {CARD}; border: 1px dashed {LINE}; border-radius: 14px;
  padding: 1.6rem 1rem; text-align: center; margin: .4rem 0;
}}
.empty-icon {{ font-size: 1.6rem; }}
.empty-title {{ font-weight: 700; color: {SLATE}; margin-top: .3rem; }}
.empty-desc {{ font-size: .83rem; color: {MUTED}; margin-top: .2rem; }}

/* ===== 岗位卡片 ===== */
.jcard-top {{ display: flex; align-items: center; gap: .55rem; flex-wrap: wrap; }}
.jgrade {{
  font-size: .72rem; font-weight: 700; padding: .08rem .55rem; border-radius: 999px;
  flex: none;
}}
.jtitle {{ font-size: 1.05rem; font-weight: 700; color: {INK}; }}
.junit {{ color: {MUTED}; font-size: .88rem; }}
.jmeta {{ color: {MUTED}; font-size: .8rem; margin: .3rem 0 .45rem; }}
.jbar {{
  height: 6px; border-radius: 999px; background: #EEF1F7; overflow: hidden; width: 100%;
}}
.jbar-fill {{ height: 100%; border-radius: 999px; transition: width .5s ease; }}
</style>
"""


def apply():
    """在 st.set_page_config 之后调用一次，注入全站 CSS。"""
    st.markdown(CSS, unsafe_allow_html=True)

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
from html import escape

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

# 按钮专用字体：优先黑体（Windows SimHei / 黑体，macOS Heiti SC），加粗后按钮文字更清晰
BUTTON_FONT = ('"SimHei", "黑体", "Heiti SC", "Microsoft YaHei", "PingFang SC", '
               '"Noto Sans CJK SC", system-ui, sans-serif')

GRADIENT = f"linear-gradient(120deg, {PRIMARY} 0%, {VIOLET} 55%, {PURPLE} 100%)"


# ---------------------------------------------------------------- 主题感知（亮/暗）
def is_dark():
    """当前主题是否为暗色。

    只认显式的 `theme.base` 配置（config.toml 或启动参数 `--theme.base dark`）。
    不读 `st.context.theme`：在无头浏览器/部分环境下它和实际渲染主题不一致，
    会导致“页面是暗色但控件是亮色”的混合状态。
    """
    try:
        return str(st.get_option("theme.base")).lower() == "dark"
    except Exception:
        return False


# ---------------------------------------------------------------- 分析工作台局部配色
# 只作用于第⑤步三维工作台，不修改全站等级色（A/B/C 语义色仍用于详情徽标）。
MATCH_SPACE = {
    "light": {
        "bg": "#FFFFFF", "panel": "#F8F9FC", "ink": "#202536", "sub": "#677083",
        "line": "#E8EBF2", "grid": "#D7DCE8", "dot": "#9BA6BC",
        "accent": "#5854DC", "accent_soft": "#F1F0FC",
    },
    "dark": {
        "bg": "#151923", "panel": "#1B2130", "ink": "#E9EDF6", "sub": "#A7B0C3",
        "line": "#30384A", "grid": "#485367", "dot": "#8693AE",
        "accent": "#AAA4FF", "accent_soft": "#292541",
    },
}


def match_space_colors():
    """当前主题下的工作台配色（返回副本，调用方可以安全改）。"""
    return dict(MATCH_SPACE["dark" if is_dark() else "light"])


# ---------------------------------------------------------------- 画像广场联动投影台配色
# 按《画像广场联动投影台改造移交》第 4 节视觉规范；只作用于画像广场，
# 不改动第⑤步 MATCH_SPACE，也不改动全站等级色。
PLAZA = {
    "light": {
        "surface": "#F7F8FC", "panel": "#FFFFFF", "subtle": "#F0F2F8",
        "ink": "#202A3C", "sub": "#69758A", "line": "#E5E9F1", "grid": "#CBD4E3",
        "dot": "#929FBB", "accent": "#6256DE", "wash": "#EEEBFC",
    },
    "dark": {
        "surface": "#10151F", "panel": "#171D29", "subtle": "#202837",
        "ink": "#E8EDF7", "sub": "#9BA9C1", "line": "#303A4E", "grid": "#3A4A65",
        "dot": "#8293B2", "accent": "#AD9CFF", "wash": "#302947",
    },
}


def plaza_colors():
    """画像广场组件配色（跟随显式 theme.base，不猜 CSS 背景）。"""
    return dict(PLAZA["dark" if is_dark() else "light"])


def dataframe(df, **kwargs):
    """表格渲染入口：跨 Streamlit 版本全宽适配（业务代码不写弃用参数）。"""
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        if (major, minor) >= (1, 49):
            kwargs.setdefault("width", "stretch")
            return st.dataframe(df, **kwargs)
    except Exception:
        pass
    kwargs.setdefault("use_container_width", True)
    return st.dataframe(df, **kwargs)


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


def full_width_kwargs():
    """st.dataframe 全宽参数跨版本适配（Streamlit ≥1.49 用 width='stretch'）。"""
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        if (major, minor) >= (1, 49):
            return {"width": "stretch"}
    except Exception:
        pass
    return {"use_container_width": True}


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


def jobs_table(jobs, limit=300):
    """检索结果表格（HTML）：岗位名称是真实链接，点击在新标签页打开原始岗位页。"""
    cols = ["岗位名称", "单位名称", "城市", "薪资", "学历", "经验", "行业"]
    rows = []
    for job in (jobs or [])[:limit]:
        name = str(job.get("岗位名称", "") or "")
        link = str(job.get("岗位链接", "") or "")
        if link.lower().startswith(("http://", "https://")):
            first = (f'<a href="{escape(link, quote=True)}" target="_blank" '
                     f'rel="noopener noreferrer">{escape(name)}</a>')
        else:
            first = escape(name)
        rest = "".join(
            f"<td>{escape(str(job.get(c, '') or '—'))}</td>" for c in cols[1:])
        rows.append(f"<tr><td>{first}</td>{rest}</tr>")
    head = "".join(f"<th>{escape(c)}</th>" for c in cols)
    total = len(jobs or [])
    more = f"（仅显示前 {limit} 条）" if total > limit else ""
    return (
        '<div class="jtable-wrap"><table class="jtable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f'<div class="jtable-cap">共 {total} 个岗位 · 点击岗位名称可在新标签页打开原始页面{more}</div>'
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
        f'<span class="jtitle">{escape(str(job.get("岗位名称", "")))}</span>'
        f'<span class="junit">{escape(str(job.get("单位名称", "")))}</span>'
        f'</div>'
        f'<div class="jmeta">💰 {escape(str(job.get("薪资", "—")))} · '
        f'等级分 {job.get("等级分", "—")}/100 · 匹配分 {p:.3f}</div>'
        f'<div class="jbar"><div class="jbar-fill" '
        f'style="width:{pct}%;background:{color}"></div></div>'
        f'</div>'
    )


# ---------------------------------------------------------------- CSS 主题
def _theme_tokens():
    """全站 CSS 令牌（亮/暗两套）。设计系统只在这里切换，组件 CSS 不写死颜色。"""
    tokens = {"FONT_STACK": FONT_STACK, "BUTTON_FONT": BUTTON_FONT}
    if is_dark():
        tokens.update(
            PAPER="#0E1117", CARD="#151923", INK="#E9EDF6", SLATE="#B7C0D0",
            MUTED="#8A94A6", LINE="#30384A", PRIMARY="#8B84F0",
            GRADIENT="linear-gradient(120deg, #4F46E5 0%, #6D28D9 55%, #7E22CE 100%)",
            SURFACE="#232A3A", BORDER_SOFT="#2A3143", HOVER="#1E2432",
            DISABLED_BG="#2A2547", DISABLED_BORDER="#4B4470",
            SIDEBAR="#12161F", TRACK="#2A3040",
            PILL_OK_FG="#34D399", PILL_OK_BG="#123B2E", PILL_OFF_BG="#2A3346",
            PILL_WARN_FG="#FBBF24", PILL_WARN_BG="#3A2C12",
            PILL_BAD_FG="#F87171", PILL_BAD_BG="#3A1D1D",
            DONE_FG="#34D399", SHADOW="rgba(0, 0, 0, .45)",
            HOVER_SHADOW="rgba(0, 0, 0, .55)",
            BTN_BG="#262C3D", BTN_BG_HOVER="#2E3547", BTN_BORDER="#3A4358",
            CAPTION_FG="#8A94A6", ALERT_FG="#E9EDF6",
        )
    else:
        tokens.update(
            PAPER="#F7F8FC", CARD="#FFFFFF", INK="#0F172A", SLATE="#475569",
            MUTED="#94A3B8", LINE="#E2E8F0", PRIMARY="#4F46E5",
            GRADIENT="linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #A855F7 100%)",
            SURFACE="#F1F5F9", BORDER_SOFT="#EEF2F7", HOVER="#F8FAFF",
            DISABLED_BG="#EDE9FE", DISABLED_BORDER="#C7C2F5",
            SIDEBAR="#FBFBFE", TRACK="#EEF1F7",
            PILL_OK_FG="#047857", PILL_OK_BG="#D1FAE5", PILL_OFF_BG="#E2E8F0",
            PILL_WARN_FG="#B45309", PILL_WARN_BG="#FEF3C7",
            PILL_BAD_FG="#B91C1C", PILL_BAD_BG="#FEE2E2",
            DONE_FG="#047857", SHADOW="rgba(15, 23, 42, .05)",
            HOVER_SHADOW="rgba(15, 23, 42, .35)",
            BTN_BG="#EEF2FF", BTN_BG_HOVER="#E0E7FF", BTN_BORDER="#C7D2FE",
            CAPTION_FG="#64748B", ALERT_FG="#0F172A",
        )
    return tokens


def _css():
    T = _theme_tokens()
    PAPER, CARD, INK = T["PAPER"], T["CARD"], T["INK"]
    SLATE, MUTED, LINE, PRIMARY = T["SLATE"], T["MUTED"], T["LINE"], T["PRIMARY"]
    GRADIENT, SURFACE, BORDER_SOFT, HOVER = T["GRADIENT"], T["SURFACE"], T["BORDER_SOFT"], T["HOVER"]
    DISABLED_BG, DISABLED_BORDER = T["DISABLED_BG"], T["DISABLED_BORDER"]
    SIDEBAR, TRACK, DONE_FG = T["SIDEBAR"], T["TRACK"], T["DONE_FG"]
    PILL_OK_FG, PILL_OK_BG = T["PILL_OK_FG"], T["PILL_OK_BG"]
    PILL_OFF_BG = T["PILL_OFF_BG"]
    PILL_WARN_FG, PILL_WARN_BG = T["PILL_WARN_FG"], T["PILL_WARN_BG"]
    PILL_BAD_FG, PILL_BAD_BG = T["PILL_BAD_FG"], T["PILL_BAD_BG"]
    SHADOW, HOVER_SHADOW = T["SHADOW"], T["HOVER_SHADOW"]
    FONT_STACK, BUTTON_FONT = T["FONT_STACK"], T["BUTTON_FONT"]
    BTN_BG, BTN_BG_HOVER, BTN_BORDER = T["BTN_BG"], T["BTN_BG_HOVER"], T["BTN_BORDER"]
    CAPTION_FG, ALERT_FG = T["CAPTION_FG"], T["ALERT_FG"]
    return f"""
<style>
/* ===== 基础版面 ===== */
.stApp {{ background: {PAPER}; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1160px; }}
html, body, [class*="css"] {{ font-family: {FONT_STACK}; }}
h1, h2, h3, h4 {{ color: {INK}; letter-spacing: .01em; }}
p, li, .stMarkdown {{ color: {SLATE}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {CAPTION_FG} !important; }}
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
.pill-ok   {{ color: {PILL_OK_FG}; background: {PILL_OK_BG}; }}
.pill-off  {{ color: {SLATE};  background: {PILL_OFF_BG}; }}
.pill-warn {{ color: {PILL_WARN_FG}; background: {PILL_WARN_BG}; }}
.pill-bad  {{ color: {PILL_BAD_FG}; background: {PILL_BAD_BG}; }}

/* ===== 检索结果表格（岗位名称可点击） ===== */
.jtable-wrap {{
  overflow-x: auto; border: 1px solid {LINE}; border-radius: 12px;
  background: {CARD}; box-shadow: 0 1px 3px {SHADOW};
}}
.jtable {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
.jtable th {{
  text-align: left; white-space: nowrap;
  padding: .6rem .85rem; background: {SURFACE}; color: {INK}; font-weight: 700;
  border-bottom: 1px solid {LINE};
}}
.jtable td {{
  padding: .55rem .85rem; color: {SLATE}; vertical-align: top;
  border-bottom: 1px solid {BORDER_SOFT};
}}
.jtable tbody tr:last-child td {{ border-bottom: none; }}
.jtable tbody tr:hover td {{ background: {HOVER}; }}
.jtable a {{ color: {PRIMARY}; font-weight: 700; text-decoration: none; }}
.jtable a:hover {{ text-decoration: underline; }}
.jtable-cap {{ margin-top: .45rem; color: {MUTED}; font-size: .78rem; }}

/* ===== 按钮 ===== */
/* 用后代选择器：带 help 的按钮会被 Streamlit 包一层 tooltip span，
   `.stButton > button` 会失配，导致字体和禁用配色回退到原生样式。 */
.stButton button {{
  border-radius: 10px; font-weight: 700; font-family: {BUTTON_FONT};
  font-size: .95rem; letter-spacing: .01em; border: 1px solid {BTN_BORDER};
  background: {BTN_BG}; color: {INK};
  -webkit-text-fill-color: {INK};
  transition: transform .08s ease, box-shadow .15s ease;
}}
/* Streamlit 会把按钮文字包在 <p> 里，而全局 p 的颜色是 SLATE，
   深色主题下就变成"黑底灰字"。这里让按钮内所有文字继承按钮颜色。 */
.stButton button p, .stButton button div, .stButton button span {{
  color: inherit !important; -webkit-text-fill-color: inherit !important;
}}
.stButton button:hover {{
  transform: translateY(-1px);
  background: {BTN_BG_HOVER};
  box-shadow: 0 6px 16px -8px {HOVER_SHADOW};
}}
.stButton button[kind="primary"] {{
  background: {GRADIENT}; border: none; color: #FFFFFF;
  -webkit-text-fill-color: #FFFFFF;
  text-shadow: 0 1px 2px rgba(15, 23, 42, .28);
  box-shadow: 0 8px 20px -8px rgba(79, 70, 229, .6);
}}
.stButton button[kind="primary"]:hover {{ background: {GRADIENT}; }}
/* 禁用/运行中：原来 opacity:.45 + 半透明白字，文字几乎看不见。
   改为浅紫实底 + 近黑黑体字，不降透明度，保持可读。 */
.stButton button:disabled {{
  opacity: 1 !important; transform: none; box-shadow: none;
  background: {DISABLED_BG} !important; border: 1px solid {DISABLED_BORDER} !important;
  color: {INK} !important; -webkit-text-fill-color: {INK} !important;
  text-shadow: none;
}}
.stButton button[kind="primary"]:disabled {{
  background: {DISABLED_BG} !important; color: {INK} !important;
}}

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
  box-shadow: 0 1px 3px {SHADOW};
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
  padding: .9rem 1.1rem; box-shadow: 0 1px 3px {SHADOW};
}}
[data-testid="stMetricLabel"] {{ color: {MUTED}; font-weight: 600; }}
[data-testid="stMetricValue"] {{ color: {INK}; font-weight: 800; }}

/* ===== 提示条圆角统一 ===== */
[data-testid="stAlert"] {{
  border-radius: 12px; border: 1px solid {LINE};
  box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
}}
/* 提示条同理：全局 p 的灰色会盖掉 success/info/warning 的文字颜色 */
[data-testid="stAlert"] p, [data-testid="stAlert"] li,
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] {{
  color: {ALERT_FG} !important; font-weight: 400;
}}

/* ===== 侧栏 ===== */
[data-testid="stSidebar"] {{
  background: {SIDEBAR}; border-right: 1px solid {LINE};
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
.stp-done {{ color: {DONE_FG}; }}
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
  height: 6px; border-radius: 999px; background: {TRACK}; overflow: hidden; width: 100%;
}}
.jbar-fill {{ height: 100%; border-radius: 999px; transition: width .5s ease; }}
</style>
"""


def apply():
    """在 st.set_page_config 之后调用一次，注入全站 CSS（随亮/暗主题切换）。"""
    st.markdown(_css(), unsafe_allow_html=True)

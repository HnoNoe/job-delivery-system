"""设计系统：全站统一的视觉令牌、CSS 主题与 Plotly 图表模板。

设计师视角的三层抽象：
1. 色彩 / 字体 / 间距令牌（PALETTE / FONT_STACK）
2. Streamlit 组件级 CSS 覆盖（CSS，hero、步骤头、按钮、卡片、侧栏）
3. Plotly 统一模板（register_template + chart() 渲染入口，
   同时承接 use_container_width 的跨版本适配，替代散落的旧写法）

业务代码只需 from theme import ...，不要在 app.py 里写裸颜色值。
"""
import json
from html import escape
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

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
DARK_KEY = "jd_dark"          # 运行时会话开关；None 表示本次会话未手动切换
THEME_TOGGLE_KEY = "jd_theme_toggle"


def _pref_path():
    """夜间模式偏好的落地文件（单机本地应用；多标签页各自会话优先）。"""
    import config
    return Path(config.DATA_DIR) / "ui_prefs.json"


def _read_pref():
    try:
        return bool(json.loads(_pref_path().read_text(encoding="utf-8"))["dark"])
    except Exception:
        return None


def _write_pref(dark: bool):
    try:
        path = _pref_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"dark": bool(dark)}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def is_dark():
    """当前是否暗色：会话开关 → 上次保存的偏好 → 显式 `theme.base` 配置。

    只认显式的 `theme.base`（config.toml 或 `--theme.base dark`），不读
    `st.context.theme`：无头/部分环境下它与实际渲染不一致，会出现半亮半暗。
    """
    try:
        override = st.session_state.get(DARK_KEY)
    except Exception:
        override = None
    if override is not None:
        return bool(override)
    saved = _read_pref()
    if saved is not None:
        return saved
    try:
        return str(st.get_option("theme.base")).lower() == "dark"
    except Exception:
        return False


def toggle_theme():
    """翻转亮/暗、写入本地偏好并重跑。"""
    dark = not is_dark()
    st.session_state[DARK_KEY] = dark
    _write_pref(dark)
    st.rerun()


def theme_toggle():
    """夜间/日间模式图标开关。

    真正承接点击的是 Streamlit 按钮（保证状态与重跑走官方链路）；同时用一段
    同源脚本把图标**放进顶栏的工具区**（与 Deploy / ⋮ 同排、由 flex 排布），
    这样不会绝对定位压住 Deploy、运行中的 Stop/Rerun 或 ⋮ 菜单。
    顶栏找不到时，按钮留在兜底位置。
    """
    dark = is_dark()
    label = "切换为日间模式" if dark else "切换为夜间模式"
    if st.button("☀️" if dark else "🌙", key=THEME_TOGGLE_KEY, help=label):
        toggle_theme()
    _theme_toggle_bridge(dark, label)


# 顶栏图标：线性风格，跟随顶栏文字色（不额外引入彩色 emoji）
_TOGGLE_ICON = {
    "moon": ('<svg viewBox="0 0 24 24" aria-hidden="true">'
             '<path d="M20.6 14.3A8.6 8.6 0 0 1 9.7 3.4 8.6 8.6 0 1 0 20.6 14.3Z"/></svg>'),
    "sun": ('<svg viewBox="0 0 24 24" aria-hidden="true">'
            '<circle cx="12" cy="12" r="4.1"/>'
            '<path d="M12 2.7v2.1M12 19.2v2.1M2.7 12h2.1M19.2 12h2.1'
            'M5.4 5.4l1.5 1.5M17.1 17.1l1.5 1.5M18.6 5.4l-1.5 1.5M6.9 17.1l-1.5 1.5"/></svg>'),
}


def _theme_toggle_bridge(dark: bool, label: str):
    """把可点击图标搬进 Streamlit 顶栏操作区（同源 iframe 内执行）。

    实现要点：
    - 点击委托挂在父文档上（capture 阶段），节点被 React 重建也不会失效；
    - 每 1.2s 自检一次：图标是否还在、该显示月亮还是太阳（以真实按钮文字为准），
      避免 Streamlit 重渲染把图标清掉；
    - 图标只是转发点击给真实 Streamlit 按钮，状态与重跑仍走官方链路。
    """
    payload = {
        "key": THEME_TOGGLE_KEY,
        "moon": json.dumps(_TOGGLE_ICON["moon"], ensure_ascii=False),
        "sun": json.dumps(_TOGGLE_ICON["sun"], ensure_ascii=False),
        "toDark": json.dumps("切换为夜间模式", ensure_ascii=False),
        "toLight": json.dumps("切换为日间模式", ensure_ascii=False),
        "initial": json.dumps(label, ensure_ascii=False),
    }
    html = """
<script>
(function () {
  var doc;
  try { doc = window.parent.document; } catch (e) { return; }
  var KEY = "%(key)s";
  var ICONS = { moon: %(moon)s, sun: %(sun)s };
  var LABELS = { dark: %(toLight)s, light: %(toDark)s };
  var host = doc.querySelector('[class*="st-key-' + KEY + '"]');
  var toolbar = doc.querySelector('[data-testid="stToolbar"]');
  if (!host || !toolbar) { return; }   // 顶栏不可用时保留兜底按钮

  function applyStyle() {
    var el = doc.getElementById("jd-theme-toggle-style");
    if (!el) {
      el = doc.createElement("style");
      el.id = "jd-theme-toggle-style";
      doc.head.appendChild(el);
    }
    el.textContent = [
      "#jd-theme-toggle{appearance:none;border:0;background:transparent;color:inherit;",
      "display:inline-flex;align-items:center;justify-content:center;width:2rem;height:2rem;",
      "padding:0;margin:0 .18rem 0 .1rem;border-radius:.5rem;cursor:pointer;flex:none;",
      "opacity:.85;transition:background .12s ease,opacity .12s ease}",
      "#jd-theme-toggle:hover{background:rgba(125,135,155,.18);opacity:1}",
      "#jd-theme-toggle:focus-visible{outline:2px solid #6256DE;outline-offset:2px}",
      "#jd-theme-toggle svg{width:17px;height:17px;fill:none;stroke:currentColor;",
      "stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}"
    ].join("");
  }

  function sync() {
    var real = doc.querySelector('[class*="st-key-' + KEY + '"] button');
    if (!real) { return; }
    var text = (real.innerText || "").trim();
    var dark = text.indexOf("\\u2600") >= 0;
    var actions = doc.querySelector('[data-testid="stToolbarActions"]') || toolbar;
    var btn = doc.getElementById("jd-theme-toggle");
    if (!btn) {
      btn = doc.createElement("button");
      btn.id = "jd-theme-toggle";
      btn.type = "button";
      btn.setAttribute("role", "button");
    }
    var label = dark ? LABELS.dark : LABELS.light;
    if (btn.title !== label) {
      btn.title = label;
      btn.setAttribute("aria-label", label);
    }
    var want = dark ? "sun" : "moon";
    if (btn.getAttribute("data-icon") !== want) {
      btn.innerHTML = ICONS[want];
      btn.setAttribute("data-icon", want);
    }
    // 每次同步都重挂一次点击（节点可能被 React 重建），转发给真实 Streamlit 按钮
    btn.onclick = function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var target = doc.querySelector('[class*="st-key-' + KEY + '"] button');
      if (target) { target.click(); }
    };
    if (btn.parentElement !== actions) { actions.insertBefore(btn, actions.firstChild); }
    doc.documentElement.setAttribute("data-jd-theme", dark ? "dark" : "light");
    // 兜底按钮移出视口（点击由上面转发）
    host.style.cssText = "position:absolute;left:-9999px;top:0;width:1px;height:1px;overflow:hidden;";
  }

  applyStyle();
  if (!doc.__jdThemeTimer) {
    doc.__jdThemeTimer = window.parent.setInterval(sync, 600);
  }
  sync();
})();
</script>
""" % payload
    components.html(html, height=0, width=0)


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
        # 定位标记强调色：暖橙与冷调中性点/靛蓝主色形成明确区分，用于「高亮配色」方案
        "spot": "#E2601A", "spot_glow": "rgba(226, 96, 26, .26)", "spot_wash": "#FCEBDF",
    },
    "dark": {
        "surface": "#10151F", "panel": "#171D29", "subtle": "#202837",
        "ink": "#E8EDF7", "sub": "#9BA9C1", "line": "#303A4E", "grid": "#3A4A65",
        "dot": "#8293B2", "accent": "#AD9CFF", "wash": "#302947",
        "spot": "#FFA057", "spot_glow": "rgba(255, 160, 87, .30)", "spot_wash": "#3A2A1C",
    },
}

# 定位标记的两种强调方案（见画像广场工具栏）
MARKER_STYLES = {
    "shape": "① 形状强调（菱形 + 准星环）",
    "color": "② 高亮配色（暖橙高亮）",
}
DEFAULT_MARKER_STYLE = "shape"


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
    """注册并启用全站统一的 Plotly 模板（幂等，按当前亮/暗令牌重建）。

    夜间模式开关切换后会再次调用，让图表文字/网格/悬浮框颜色跟着换，
    避免“深色页面 + 深色图表字”。
    """
    T = _theme_tokens()
    tpl = go.layout.Template(
        layout=dict(
            font=dict(family=T["FONT_STACK"], size=13, color=T["SLATE"]),
            colorway=CHART_SEQ,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=16, r=16, t=52, b=16),
            title=dict(font=dict(size=15, color=T["INK"], family=T["FONT_STACK"]),
                       x=0.02, xanchor="left"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1.0, xanchor="right",
                        font=dict(size=12), bgcolor="rgba(0,0,0,0)",
                        title=dict(text="")),
            hoverlabel=dict(bgcolor=T["CARD"], bordercolor=T["LINE"],
                            font=dict(family=T["FONT_STACK"], size=12, color=T["INK"])),
            xaxis=dict(gridcolor="rgba(0,0,0,0)", linecolor=T["LINE"], tickfont=dict(size=12),
                       zerolinecolor=T["LINE"]),
            yaxis=dict(gridcolor=T["LINE"], linecolor="rgba(0,0,0,0)", tickfont=dict(size=12),
                       zerolinecolor=T["LINE"]),
            bargap=0.28,
        )
    )
    pio.templates["jd"] = tpl
    pio.templates.default = "jd"


# 模块导入时先注册一次默认模板；`apply()` 会按当前亮/暗令牌重新注册。
# 注意：这里不能立即调用——`_theme_tokens()` 定义在本文件靠后位置。


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


def _toggle_css():
    """主题开关的兜底样式。

    正常情况下脚本会把图标放进顶栏工具区（与 Deploy / ⋮ 同排、flex 排布，
    不会遮住任何已有控件）；只有脚本被禁用/顶栏结构变化时，按钮才留在正文
    顶部右对齐的普通位置。**这里不使用 !important**，便于脚本用内联样式接管。
    """
    T = _theme_tokens()
    return f"""
<style>
/* ===== 夜间模式图标开关（兜底位置：正文右上角，不覆盖任何控件） ===== */
[class*="st-key-{THEME_TOGGLE_KEY}"] {{
  display: flex; justify-content: flex-end; padding: 0; margin: 0;
}}
[class*="st-key-{THEME_TOGGLE_KEY}"] button {{
  width: 34px; height: 34px; min-height: 34px; padding: 0;
  border-radius: 999px; display: grid; place-items: center;
  background: {T["CARD"]}; color: {T["INK"]};
  border: 1px solid {T["LINE"]}; box-shadow: 0 1px 4px {T["SHADOW"]};
}}
[class*="st-key-{THEME_TOGGLE_KEY}"] button:hover {{
  transform: none; background: {T["BTN_BG_HOVER"]};
}}
[class*="st-key-{THEME_TOGGLE_KEY}"] button:focus-visible {{
  outline: 2px solid {T["PRIMARY"]}; outline-offset: 2px;
}}
[class*="st-key-{THEME_TOGGLE_KEY}"] button p {{
  font-size: 16px; line-height: 1; margin: 0;
}}
</style>
"""


def _dark_css():
    """夜间模式下覆盖 Streamlit 自带控件（这些控件不跟随我们的令牌）。"""
    T = _theme_tokens()
    return f"""
<style>
/* ===== 夜间模式：兜住 Streamlit 自带外壳与控件 ===== */
html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background: {T["PAPER"]} !important; color: {T["SLATE"]} !important;
}}
[data-testid="stHeader"] {{ background: {T["PAPER"]} !important; }}
[data-testid="stHeader"] * {{ color: {T["SLATE"]} !important; }}
[data-testid="stToolbar"] {{ background: transparent !important; }}
[data-testid="stToolbar"] button, [data-testid="stToolbar"] span,
[data-testid="stToolbar"] p {{ color: {T["SLATE"]} !important; }}
[data-testid="stToolbarActions"] button:hover {{ background: {T["SURFACE"]} !important; }}
[data-testid="stDecoration"] {{ background: {T["PRIMARY"]} !important; }}

/* 侧栏 */
[data-testid="stSidebar"], [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] {{
  background: {T["SIDEBAR"]} !important;
}}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] li,
[data-testid="stSidebar"] span, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown {{ color: {T["SLATE"]} !important; }}
[data-testid="stSidebar"] hr {{ border-top-color: {T["LINE"]} !important; }}

/* 正文文字与标签 */
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span:not([class*="pill"]):not([class*="stp"]) {{
  color: {T["SLATE"]};
}}
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label,
[data-testid="stWidgetLabel"] span {{ color: {T["SLATE"]} !important; }}
[data-testid="stCaptionContainer"], .stCaption, [data-testid="stCaptionContainer"] p {{
  color: {T["CAPTION_FG"]} !important;
}}

/* 输入类控件 */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="base-input"] {{
  background: {T["CARD"]} !important; border-color: {T["LINE"]} !important;
}}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
[data-baseweb="base-input"] input {{
  background: {T["CARD"]} !important; color: {T["INK"]} !important;
  -webkit-text-fill-color: {T["INK"]} !important;
}}
[data-baseweb="input"] input::placeholder, [data-baseweb="textarea"] textarea::placeholder {{
  color: {T["MUTED"]} !important;
}}

/* Streamlit 1.66 起文本/下拉输入改用 react-aria 结构（没有 data-baseweb） */
.react-aria-TextField > div, .react-aria-ComboBox > div {{
  background: {T["CARD"]} !important; border-color: {T["LINE"]} !important;
}}
.react-aria-TextField input, .react-aria-ComboBox input, .react-aria-TextField textarea {{
  background: transparent !important; color: {T["INK"]} !important;
  -webkit-text-fill-color: {T["INK"]} !important;
}}
.react-aria-TextField input::placeholder, .react-aria-ComboBox input::placeholder {{
  color: {T["MUTED"]} !important; -webkit-text-fill-color: {T["MUTED"]} !important;
}}
.react-aria-TextField svg, .react-aria-ComboBox svg {{
  color: {T["SLATE"]} !important; fill: {T["SLATE"]} !important;
}}
[data-testid="stNumberInput"] button {{
  background: {T["SURFACE"]} !important; color: {T["INK"]} !important;
  border-color: {T["LINE"]} !important;
}}
[data-testid="stNumberInput"] button svg {{ fill: {T["INK"]} !important; }}
[data-testid="stFileUploaderDropzone"], [data-testid="stFileUploaderDropzone"] div {{
  background: {T["CARD"]} !important; color: {T["SLATE"]} !important;
}}
[data-testid="stFileUploaderDropzone"] p, [data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] small {{ color: {T["SLATE"]} !important; }}
[data-baseweb="select"] > div, [data-baseweb="select"] div[role="button"] {{
  background: {T["CARD"]} !important; border-color: {T["LINE"]} !important;
  color: {T["INK"]} !important;
}}
[data-baseweb="select"] svg {{ fill: {T["SLATE"]} !important; }}
[data-baseweb="popover"] div, [data-baseweb="popover"] ul, [role="listbox"] {{
  background: {T["CARD"]} !important; border-color: {T["LINE"]} !important;
}}
[role="option"] {{ color: {T["INK"]} !important; background: {T["CARD"]} !important; }}
[role="option"]:hover, [role="option"][aria-selected="true"], [role="option"][data-focus-visible] {{
  background: {T["SURFACE"]} !important;
}}

/* 单选 / 复选 / 开关 / 滑块 */
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p,
[data-testid="stToggle"] label p {{ color: {T["SLATE"]} !important; }}
[data-testid="stSlider"] [data-baseweb="slider"] div {{ color: {T["SLATE"]}; }}

/* 折叠卡片 / 提示条 / 指标卡 / 代码块 */
[data-testid="stExpander"] details {{ background: {T["CARD"]} !important; color: {T["SLATE"]} !important; }}
[data-testid="stExpander"] details > div {{ background: {T["CARD"]} !important; color: {T["SLATE"]} !important; }}
[data-testid="stExpander"] summary {{
  background: {T["CARD"]} !important; color: {T["INK"]} !important;
}}
[data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span,
[data-testid="stExpander"] details > div p, [data-testid="stExpander"] details > div li {{
  color: {T["SLATE"]} !important;
}}
[data-testid="stExpander"] summary svg {{ fill: {T["SLATE"]} !important; }}
[data-testid="stAlert"] {{ background: {T["SURFACE"]} !important; border-color: {T["LINE"]} !important; }}
[data-testid="stAlert"] p, [data-testid="stAlert"] li {{ color: {T["ALERT_FG"]} !important; }}
[data-testid="stMetric"] {{ background: {T["CARD"]} !important; border-color: {T["LINE"]} !important; }}
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] {{ color: {T["MUTED"]} !important; }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] div {{ color: {T["INK"]} !important; }}
[data-testid="stMetricDelta"] {{ color: {T["SLATE"]} !important; }}
[data-testid="stDataFrame"], [data-testid="stDataFrame"] > div {{ background: {T["CARD"]} !important; }}
/* 表格是 canvas 绘制、跟随 Streamlit 主题；用反相 + 色相回正在暗色下看清内容 */
[data-testid="stDataFrame"] canvas {{ filter: invert(.9) hue-rotate(180deg); }}
[data-testid="stDataFrame"] * {{ color: {T["SLATE"]}; border-color: {T["LINE"]} !important; }}
[data-testid="stCodeBlock"], [data-testid="stCodeBlock"] pre, pre, code {{
  background: {T["SURFACE"]} !important; color: {T["INK"]} !important;
  border-color: {T["LINE"]} !important;
}}
[data-testid="stCodeBlock"] code span {{ color: {T["INK"]} !important; }}
[data-testid="stFileUploaderDropzone"] {{
  background: {T["CARD"]} !important; border-color: {T["LINE"]} !important;
}}
[data-testid="stFileUploaderDropzone"] * {{ color: {T["SLATE"]} !important; }}
[data-testid="stTabs"] button {{ color: {T["SLATE"]} !important; }}
[data-testid="stTabs"] button[aria-selected="true"] {{ color: {T["INK"]} !important; }}
hr {{ border-color: {T["LINE"]} !important; }}
[data-testid="stDivider"] {{ background: {T["LINE"]} !important; }}
</style>
"""


def apply():
    """在 st.set_page_config 之后调用一次：注入全站 CSS、注册图表模板、
    渲染右上角的夜间模式开关（随当前亮/暗切换）。"""
    register_template()
    st.markdown(_css(), unsafe_allow_html=True)
    if is_dark():
        st.markdown(_dark_css(), unsafe_allow_html=True)
    st.markdown(_toggle_css(), unsafe_allow_html=True)
    theme_toggle()


# 文件末尾再注册一次：此时 `_theme_tokens()` 已定义，且没有运行上下文时
# `is_dark()` 会自动回退到 config.toml 的 theme.base。
try:
    register_template()
except Exception:  # 极早期导入（无 Streamlit 运行上下文）时不阻塞
    pass

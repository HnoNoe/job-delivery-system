"""画像广场「联动投影台」：数据准备 + Streamlit 组件桥接。

页面目标（见 `交给DeepSeek-画像广场联动投影台改造移交.md`）：
- 左侧三维总览 + 右侧 XY / XZ 两个二维投影 + 下方选中人物详情；
- 三张图使用同一批用户、同一个 `user_id` 选中态，任意视图点击都联动；
- 指标空间与 PCA 语义空间共用同一套展示数据接口；
- 有效集合、缺失原因、坐标范围一次算好，三图共用，不补零、不臆造维度。

本模块只做数据与桥接，不修改投递流程、经历权重或任何业务评分。
纯函数（`build_metric_space` / `compute_pca_space` / `build_payload`）便于单元测试；
`get_space` 负责按数据版本缓存，`render` 负责挂载 `components/profile_plaza/`。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

import db
import theme

COMPONENT_NAME = "profile_plaza"

# 七个可选指标：字段 ID -> 展示元数据（标签、单位、格式、默认显示范围）
AXIS_META = {
    "GPA": {"label": "GPA（归一）", "unit": "", "kind": "ratio", "decimals": 2},
    "排名优秀度": {"label": "排名优秀度", "unit": "", "kind": "ratio", "decimals": 2},
    "经历段数": {"label": "经历段数", "unit": "段", "kind": "count", "decimals": 0},
    "技能数": {"label": "技能数", "unit": "项", "kind": "count", "decimals": 0},
    "累计投递": {"label": "累计投递", "unit": "次", "kind": "count", "decimals": 0},
    "进面试率": {"label": "进面试率", "unit": "%", "kind": "percent", "decimals": 0},
    "平均匹配分": {"label": "平均匹配分", "unit": "", "kind": "score", "decimals": 3},
}
METRIC_AXES = tuple(AXIS_META)
DEFAULT_AXES = ("GPA", "技能数", "经历段数")
SEMANTIC_AXES = ("PC1", "PC2", "PC3")

_MISSING_REASON = {
    "GPA": "缺少 GPA（未填写或无法解析）",
    "排名优秀度": "缺少专业排名（无法解析）",
    "进面试率": "进面试率未知（尚无已标注结果）",
    "平均匹配分": "平均匹配分未知（尚无投递记录）",
}
_MODE_LABEL = {"metrics": "指标空间", "semantic": "语义空间（式一 PCA）"}


# ---------------------------------------------------------------- 组件路径
def _component_dir() -> Path:
    """源码运行用模块同目录；PyInstaller 便携版用 _MEIPASS。"""
    roots = [Path(__file__).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    for root in roots:
        candidate = root / "components" / COMPONENT_NAME
        if candidate.joinpath("index.html").is_file():
            return candidate
    return roots[0] / "components" / COMPONENT_NAME


_COMPONENT = None


def _get_component():
    global _COMPONENT
    if _COMPONENT is None:
        _COMPONENT = components.declare_component(COMPONENT_NAME, path=str(_component_dir()))
    return _COMPONENT


def render(payload: dict, key: str = "profile_plaza_space"):
    """把组件参数交给前端；返回组件回传的选中事件（dict 或 None）。"""
    return _get_component()(payload=payload, key=key, default=None)


# ---------------------------------------------------------------- 小工具
def _finite(value):
    """转成有限 float；空值/非法值返回 None（**不补 0**）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _id(value) -> str:
    """稳定 ID：统一转字符串，避免前后端 int/str 混用导致选错人。"""
    return str(value)


def _clean_vec(value):
    """把 JSON 向量整理成有限 float 列表；任何非有限/非数值都拒绝。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, (list, tuple)) or not value:
        return None
    out = []
    for item in value:
        f = _finite(item)
        if f is None:
            return None
        out.append(f)
    return out


def _nice_step(span: float, target: int = 4) -> float:
    """取 1/2/2.5/5/10 系列的“好看”步长。"""
    if span <= 0:
        return 1.0
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def _position(value: float, domain) -> float:
    lo, hi = float(domain[0]), float(domain[1])
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _is_constant(values) -> bool:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return True
    return (max(clean) - min(clean)) <= 1e-12


def _domain(meta: dict, values) -> list[float]:
    """轴显示范围：比例固定 0~1；计数从 0 起；其余按数据留边。"""
    kind = meta["kind"]
    clean = [v for v in values if v is not None]
    if kind in ("ratio", "percent"):
        # 理论范围 0~1；若上游数据出现越界值，扩展显示范围而不是把点裁到边缘
        lo = min([0.0] + clean) if clean else 0.0
        hi = max([1.0] + clean) if clean else 1.0
        if hi <= lo:
            hi = lo + 1.0
        return [float(lo), float(hi)]
    if kind == "count":
        hi = max(1.0, max(clean) if clean else 1.0)
        step = _nice_step(hi, 4)
        return [0.0, float(math.ceil(hi / step) * step)]
    # score / pca
    if not clean:
        return [0.0, 1.0]
    lo, hi = min(clean), max(clean)
    if hi - lo <= 1e-12:
        pad = 0.05 if kind == "score" else 1.0
        lo, hi = lo - pad, hi + pad
        if kind == "score":
            lo, hi = max(0.0, lo), min(1.0, hi)
            if hi <= lo:
                hi = min(1.0, lo + 0.1)
                lo = max(0.0, hi - 0.1)
    else:
        pad = (hi - lo) * 0.08
        lo, hi = lo - pad, hi + pad
    return [float(lo), float(hi)]


def _value_label(axis_id: str, value: float) -> str:
    """坐标轴刻度/详情用的展示字符串（带单位）。"""
    meta = AXIS_META.get(axis_id)
    if meta is None:  # PCA
        return "%.2f" % value
    kind = meta["kind"]
    if kind == "percent":
        return "%.0f%%" % (value * 100)
    if kind == "count":
        txt = "%d" % int(round(value))
        return txt + (" " + meta["unit"] if meta["unit"] else "")
    if kind == "score":
        return "%.3f" % value
    return "%.2f" % value


def _plain_label(axis_id: str, value: float) -> str:
    """纯数值标签（刻度用，不带单位）。"""
    meta = AXIS_META.get(axis_id)
    if meta is None:
        return "%.2f" % value
    kind = meta["kind"]
    if kind == "percent":
        return "%.0f%%" % (value * 100)
    if kind == "count":
        return "%d" % int(round(value))
    if kind == "score":
        return "%.3f" % value
    return "%.2f" % value


def _ticks(meta: dict, domain) -> list[dict]:
    """生成 4~6 个刻度（含 value 与 pos），计数轴保证整数。"""
    lo, hi = float(domain[0]), float(domain[1])
    kind = meta["kind"]
    values = []
    if kind == "count":
        step = _nice_step(max(hi, 1.0), 4)
        v = 0.0
        guard = 0
        while v <= hi + 1e-9 and guard < 10:
            values.append(v)
            v += step
            guard += 1
        if values and values[-1] < hi - 1e-9:
            values.append(hi)
    else:
        n = 4
        values = [lo + (hi - lo) * i / n for i in range(n + 1)]
    axis_id = meta.get("_axis_id", "")
    return [{"value": round(float(v), 6), "label": _plain_label(axis_id, v),
             "pos": round(_position(v, domain), 6)} for v in values]


def _axis_payload(axis_id: str, values) -> dict:
    if axis_id in AXIS_META:
        meta = dict(AXIS_META[axis_id])
    else:
        meta = {"label": axis_id, "unit": "", "kind": "pca", "decimals": 2}
    meta["_axis_id"] = axis_id
    domain = _domain(meta, values)
    return {
        "id": axis_id,
        "label": meta["label"],
        "unit": meta["unit"],
        "kind": meta["kind"],
        "domain": [round(float(domain[0]), 6), round(float(domain[1]), 6)],
        "ticks": _ticks(meta, domain),
        "constant": _is_constant(values),
        "note": "该轴在当前数据中无变化" if _is_constant(values) else "",
    }


def _base_profile(record: dict) -> dict:
    uid = _id(record.get("user_id"))
    name = record.get("姓名") or ("用户%s" % uid)
    return {
        "user_id": uid,
        "name": str(name),
        "school": str(record.get("学校") or ""),
        "major": str(record.get("专业") or ""),
    }


def _missing_reason(axis_id: str) -> str:
    return _MISSING_REASON.get(axis_id, "缺少 %s" % AXIS_META.get(axis_id, {}).get("label", axis_id))


def _coords_from_values(values, axes) -> list[float]:
    return [round(_position(v, axis["domain"]), 6) for v, axis in zip(values, axes)]


# ---------------------------------------------------------------- 指标空间
def build_metric_space(df, axes) -> dict:
    """把用户指标表整理成三图共享空间。

    visible_users = 所选 X/Y/Z 三轴均有有限数值的用户；缺任一轴的用户进入
    `excluded` 并写明缺失原因，三图一致排除，不补 0。
    """
    axes = list(axes)
    if len(axes) != 3:
        raise ValueError("指标空间需要恰好 3 个轴")
    if len(set(axes)) != 3:
        raise ValueError("X/Y/Z 轴不能重复")
    unknown = [a for a in axes if a not in AXIS_META]
    if unknown:
        raise ValueError("未知指标轴：%s" % "、".join(unknown))

    profiles, visible_raw, excluded, values_by_axis = {}, [], [], {a: [] for a in axes}
    records = df.to_dict("records") if hasattr(df, "to_dict") else list(df or [])
    for record in records:
        base = _base_profile(record)
        uid = base["user_id"]
        values, missing = [], []
        for axis_id in axes:
            value = _finite(record.get(axis_id))
            values.append(value)
            if value is None:
                missing.append(axis_id)
            else:
                values_by_axis[axis_id].append(value)
        profiles[uid] = dict(base, values=values, coords=None)
        if missing:
            excluded.append(dict(base, reason="；".join(_missing_reason(a) for a in missing),
                                 missing=[AXIS_META[a]["label"] for a in missing]))
        else:
            visible_raw.append(dict(base, values=values))

    axes_payload = [_axis_payload(a, values_by_axis[a]) for a in axes]
    users = []
    for item in visible_raw:
        coords = _coords_from_values(item["values"], axes_payload)
        user = dict(item, coords=coords,
                    display=[_value_label(a, v) for a, v in zip(axes, item["values"])])
        users.append(user)
        profiles[item["user_id"]]["coords"] = coords
        profiles[item["user_id"]]["display"] = user["display"]
        profiles[item["user_id"]]["missing"] = []

    # 被排除用户也保留下原始数值，选中时详情仍可显示（缺失项为 None）
    for base in excluded:
        uid = base["user_id"]
        profiles[uid].setdefault("display", [
            _value_label(a, v) if v is not None else "—"
            for a, v in zip(axes, profiles[uid]["values"])])
        profiles[uid]["missing"] = base.get("missing", [])

    notes = []
    if not users:
        notes.append("当前所选三轴没有同时有值的用户：请换一组人人都有数据的轴，或补全用户信息。")
    if any(a["note"] for a in axes_payload):
        notes.append("；".join("%s：%s" % (a["label"], a["note"]) for a in axes_payload if a["note"]))
    return {
        "mode": "metrics", "dims": 3, "axes": axes_payload,
        "users": users, "excluded": excluded, "profiles": profiles,
        "total_count": len(records), "visible_count": len(users), "notes": notes,
    }


# ---------------------------------------------------------------- 语义空间
def compute_pca_space(profiles: dict, vectors: dict) -> dict:
    """一次 PCA 计算，供 3D/XY/XZ 共用；向量不足/维度不一致时明确降级。

    profiles: {user_id(str): 基础资料 dict}
    vectors:  {user_id(str): 原始向量（list/JSON str）}
    返回包含 axes/users/excluded/profiles 的空间；无法展示时返回 {"error": ...}。
    """
    cleaned, bad = {}, []
    dims_count = {}
    for uid, vec in (vectors or {}).items():
        uid = _id(uid)
        clean = _clean_vec(vec)
        if clean is None:
            bad.append((uid, "向量含无效数值或为空"))
            continue
        cleaned[uid] = clean
        dims_count[len(clean)] = dims_count.get(len(clean), 0) + 1
    if not cleaned:
        return {"error": "语义空间不可用：还没有可用的画像快照向量（profile_pool 为空）。",
                "mode": "semantic", "dims": 0, "axes": [], "users": [],
                "excluded": [], "profiles": {}, "total_count": len(profiles or {}),
                "visible_count": 0, "notes": []}

    # 以出现最多的维度为基准；维度不同不能混在一个空间里
    base_dim = max(dims_count, key=lambda d: (dims_count[d], d))
    valid_ids = [uid for uid in cleaned if len(cleaned[uid]) == base_dim]
    excluded = []
    for uid, reason in bad:
        base = (profiles or {}).get(uid, {"user_id": uid, "name": "用户%s" % uid,
                                          "school": "", "major": ""})
        excluded.append(dict(base, reason=reason, missing=["画像向量"]))
    for uid in cleaned:
        if len(cleaned[uid]) != base_dim:
            base = (profiles or {}).get(uid, {"user_id": uid, "name": "用户%s" % uid,
                                              "school": "", "major": ""})
            excluded.append(dict(base,
                                  reason="画像向量维度不一致（%d，基准 %d），未参与同一次 PCA"
                                         % (len(cleaned[uid]), base_dim),
                                  missing=["画像向量"]))
    if len(valid_ids) < 2:
        return {"error": "语义空间不可用：至少需要 2 位有画像快照的用户（当前 %d 位）。"
                         % len(valid_ids),
                "mode": "semantic", "dims": 0, "axes": [], "users": [],
                "excluded": excluded, "profiles": profiles or {},
                "total_count": len(profiles or {}), "visible_count": 0, "notes": []}

    X = np.vstack([cleaned[uid] for uid in valid_ids]).astype(float)
    centered = X - X.mean(axis=0)
    try:
        _, singular, vt = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        return {"error": "语义空间不可用：PCA 计算失败（%s）。" % exc,
                "mode": "semantic", "dims": 0, "axes": [], "users": [],
                "excluded": excluded, "profiles": profiles or {},
                "total_count": len(profiles or {}), "visible_count": 0, "notes": []}
    tol = max(float(singular[0]) * 1e-9, 1e-12) if singular.size else 0.0
    rank = int((singular > tol).sum())
    if rank < 2:
        return {"error": "语义空间不可用：有效秩仅为 %d（用户向量过于共线/重复），"
                         "无法形成可解释的二维投影。" % rank,
                "mode": "semantic", "dims": 0, "axes": [], "users": [],
                "excluded": excluded, "profiles": profiles or {},
                "total_count": len(profiles or {}), "visible_count": 0, "notes": []}

    dims = min(3, rank)
    proj = centered @ vt.T[:, :dims]  # 唯一一次投影；三图都从这里取
    axes_payload = []
    for j in range(dims):
        axis_id = "PC%d" % (j + 1)
        axes_payload.append(_axis_payload(axis_id, proj[:, j].tolist()))
    users, updated_profiles = [], dict(profiles or {})
    for row, uid in enumerate(valid_ids):
        coords = _coords_from_values(proj[row, :dims].tolist(), axes_payload)
        base = (profiles or {}).get(uid) or {"user_id": uid, "name": "用户%s" % uid,
                                             "school": "", "major": ""}
        item = dict(base, values=[float(v) for v in proj[row, :dims]],
                    coords=coords,
                    display=[_value_label("PC%d" % (j + 1), float(v))
                             for j, v in enumerate(proj[row, :dims])])
        users.append(item)
        updated_profiles[uid] = dict(item)

    # 未提供向量的用户也要能作为“定位用户”显示，只是无法定位
    for uid, prof in updated_profiles.items():
        prof.setdefault("values", [None] * dims)
        prof.setdefault("coords", None)
        prof.setdefault("display", ["—"] * dims)
        prof.setdefault("missing", []) 

    notes = ["PCA：%d 位用户参与，有效秩 %d" % (len(valid_ids), rank)]
    total_var = float((singular ** 2).sum())
    if total_var > 0 and singular.size >= dims:
        ratios = [float((singular[j] ** 2) / total_var) for j in range(dims)]
        notes.append("解释方差 " + " / ".join("PC%d %.0f%%" % (j + 1, r * 100)
                                             for j, r in enumerate(ratios)))
    if dims < 3:
        notes.append("PC3 不可用（有效秩 %d），三维联动已降级为二维投影；未补造第三个维度" % rank)
    return {
        "mode": "semantic", "dims": dims, "axes": axes_payload,
        "users": users, "excluded": excluded, "profiles": updated_profiles,
        "total_count": len(profiles or {}), "visible_count": len(users),
        "notes": notes, "rank": rank,
    }


def build_semantic_space(df, latest_vectors=None) -> dict:
    """读取每位用户最新画像快照向量，构造共享 PCA 空间。

    latest_vectors 传入 {user_id: user_vec} 时跳过数据库（便于测试/验证）。
    """
    records = df.to_dict("records") if hasattr(df, "to_dict") else list(df or [])
    profiles = {_id(r.get("user_id")): _base_profile(r) for r in records}
    if latest_vectors is None:
        latest_vectors = {}
        try:
            with db.get_conn() as conn:
                rows = conn.execute(
                    "SELECT p.user_id, p.user_vec FROM profile_pool p "
                    "JOIN (SELECT user_id, MAX(snap_id) AS ms FROM profile_pool GROUP BY user_id) m "
                    "ON p.user_id=m.user_id AND p.snap_id=m.ms").fetchall()
            for row in rows:
                latest_vectors[_id(row["user_id"])] = row["user_vec"]
        except Exception as exc:  # 数据表缺失/损坏时给出可解释错误
            return {"error": "语义空间不可用：读取画像快照失败（%s）。" % exc,
                    "mode": "semantic", "dims": 0, "axes": [], "users": [],
                    "excluded": [], "profiles": profiles,
                    "total_count": len(profiles), "visible_count": 0, "notes": []}

    space = compute_pca_space(profiles, latest_vectors)
    if space.get("error"):
        return space

    known = {u["user_id"] for u in space["users"]}
    excluded_ids = {e["user_id"] for e in space["excluded"]}
    for uid, prof in profiles.items():
        if uid not in known and uid not in excluded_ids:
            space["excluded"].append(dict(prof,
                                          reason="缺少画像快照（尚无式一用户向量）",
                                          missing=["画像快照"]))
    space["total_count"] = len(profiles)
    return space


# ---------------------------------------------------------------- 选中与组件参数
def resolve_selected(space: dict, selected_user_id) -> tuple:
    """返回 (选中 user_id, 说明)。用户仍在就用它；已被删除才回退到首个可见用户。"""
    profiles = (space or {}).get("profiles") or {}
    selected = _id(selected_user_id) if selected_user_id not in (None, "") else None
    if selected in profiles:
        return selected, ""
    users = (space or {}).get("users") or []
    fallback = users[0]["user_id"] if users else (next(iter(profiles), None))
    if fallback is None:
        return None, "当前没有可定位的用户。"
    name = profiles.get(fallback, {}).get("name") or ("用户%s" % fallback)
    return fallback, "原定位用户已不在当前数据集中，已回到 %s。" % name


def build_payload(space: dict, selected_user_id, view_mode: str = "linked3d") -> dict:
    """把空间 + 选中态整理为组件参数；选中用户缺轴时保留详情但不伪造高亮。"""
    axes = (space or {}).get("axes") or []
    profiles = (space or {}).get("profiles") or {}
    selected, selection_note = resolve_selected(space, selected_user_id)
    visible_ids = {u["user_id"] for u in (space or {}).get("users") or []}
    selected_visible = selected in visible_ids
    selected_payload = None
    if selected and selected in profiles:
        prof = profiles[selected]
        values = list(prof.get("values") or [])
        if len(values) < len(axes):
            values += [None] * (len(axes) - len(values))
        display = []
        for axis, value in zip(axes, values):
            display.append(_value_label(axis["id"], value) if value is not None else "—")
        missing = [axis["label"] for axis, value in zip(axes, values) if value is None]
        selected_payload = {
            "user_id": selected,
            "name": prof.get("name") or ("用户%s" % selected),
            "school": prof.get("school") or "",
            "major": prof.get("major") or "",
            "values": [None if v is None else round(float(v), 6) for v in values],
            "display": display,
            "visible": selected_visible,
            "missing_axes": missing,
        }
        if not selected_visible and not selection_note:
            selection_note = ("当前所选指标不足（缺少 %s），无法在三张图中定位；"
                              "可换一组有数据的轴，或补全资料。" % "、".join(missing or ["所需轴"]))
    dims = int((space or {}).get("dims") or 0)
    mode = (space or {}).get("mode") or "metrics"
    view = view_mode if view_mode in ("linked3d", "flat2d") else "linked3d"
    if dims < 3:
        view = "flat2d"
    payload = {
        "data_revision": (space or {}).get("revision", ""),
        "mode": mode,
        "mode_label": _MODE_LABEL.get(mode, mode),
        "view_mode": view,
        "dims": dims,
        "axes": axes,
        "users": (space or {}).get("users") or [],
        "excluded": (space or {}).get("excluded") or [],
        "total_count": int((space or {}).get("total_count") or 0),
        "visible_count": int((space or {}).get("visible_count") or 0),
        "selected_user_id": selected,
        "selected_visible": selected_visible,
        "selected_user": selected_payload,
        "selection_note": selection_note,
        "notes": (space or {}).get("notes") or [],
        "theme": theme.plaza_colors(),
        "labels": {"subtitle": "同一用户在三个视图中同步高亮；原始数值不修改"},
    }
    if (space or {}).get("error"):
        payload["error"] = space["error"]
    return payload


def parse_event(value, space: dict):
    """校验组件回传事件：只接受当前数据版本、当前可见集合中的 user_id。"""
    if not isinstance(value, dict):
        return None
    if value.get("event") != "select_user":
        return None
    if value.get("data_revision") != (space or {}).get("revision"):
        return None
    uid = _id(value.get("user_id"))
    visible = {u["user_id"] for u in (space or {}).get("users") or []}
    return uid if uid in visible else None


# ---------------------------------------------------------------- 数据版本与缓存
def _source_revision(mode: str, axes) -> str:
    """数据版本：用户/经历/任务/画像快照的计数与最大编号足够感知增量变化。"""
    try:
        with db.get_conn() as conn:
            u = conn.execute("SELECT COUNT(*), COALESCE(MAX(user_id), 0) FROM user_records").fetchone()
            e = conn.execute("SELECT COUNT(*), COALESCE(MAX(exp_id), 0) FROM experience_items").fetchone()
            t = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(task_id), 0), "
                "COALESCE(ROUND(SUM(COALESCE(match_score, 0)), 6), 0) FROM delivery_tasks"
            ).fetchone()
            p = conn.execute("SELECT COUNT(*), COALESCE(MAX(snap_id), 0) FROM profile_pool").fetchone()
        raw = json.dumps([mode, list(axes), [int(x) for x in u], [int(x) for x in e],
                          [int(t[0]), int(t[1]), float(t[2])], [int(x) for x in p]],
                         ensure_ascii=False)
    except Exception:
        raw = json.dumps([mode, list(axes)], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def get_space(mode: str, axes, df, use_cache: bool = True) -> dict:
    """带数据版本缓存的入口：用户切换只改选中态，不重复计算 PCA。"""
    axes = tuple(axes)
    revision = _source_revision(mode, axes)
    cache_key = "%s|%s|%s" % (mode, ",".join(axes), revision)
    if use_cache:
        cache = st.session_state.get("profile_plaza_cache")
        if isinstance(cache, dict) and cache.get("key") == cache_key:
            return cache["space"]

    if mode == "semantic":
        space = build_semantic_space(df)
    else:
        space = build_metric_space(df, axes)
    space["revision"] = revision
    if use_cache:
        try:
            st.session_state["profile_plaza_cache"] = {"key": cache_key, "space": space}
        except Exception:
            pass
    return space

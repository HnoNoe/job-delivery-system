"""桌面端主程序（tkinter）——注册登录 + 简历管理 + 画像对比 + 岗位池。

替代 Streamlit 的本地原生界面：双击 exe 直接弹出窗口，不依赖浏览器。
网络操作全部放后台线程，界面不卡。
"""
import json
import os
import queue
import threading
import webbrowser

import config

APP_TITLE = "智投链 · 求职批量投递系统"


def _bg(fn, on_done):
    """后台执行 fn()，结果经队列回主线程；on_done(ok, result_or_err)。"""
    q = queue.Queue()

    def worker():
        try:
            q.put((True, fn()))
        except Exception as e:
            q.put((False, e))

    threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            ok, res = q.get_nowait()
        except queue.Empty:
            _root().after(100, poll)
            return
        on_done(ok, res)

    _root().after(100, poll)


_ROOT = None


def _root():
    return _ROOT


# ---------------- 画像对比图 ----------------

def build_compare_chart(owner):
    """公开画像（他人=对比）+ 我的快照 → plotly 三维空间图 HTML。返回文件路径。"""
    import numpy as np
    import plotly.graph_objects as go

    import mydata

    profiles = mydata.list_public_profiles(exclude_owner=owner)
    mine = [p for p in mydata.list_public_profiles(exclude_owner=None)
            if p["owner"] == owner]
    vectors, labels, groups = [], [], []
    for p in profiles:
        v = json.loads(p["user_vec"] or "null")
        if v:
            vectors.append(v)
            labels.append(p["owner"])
            groups.append("其他用户")
    for p in mine:
        v = json.loads(p["user_vec"] or "null")
        if v:
            vectors.append(v)
            labels.append(p["owner"] + "（我）")
            groups.append("我")

    out = os.path.join(config.DATA_DIR, "plaza_compare.html")
    if len(vectors) < 2:
        with open(out, "w", encoding="utf-8") as f:
            f.write("<meta charset='utf-8'><body style='font-family:sans-serif'>"
                    "<h3>画像广场数据不足</h3><p>至少需要 2 个公开画像才能生成空间对比图。"
                    "请先在网页端完成一次投递闭环发布画像，或等待其他用户发布。</p></body>")
        return out

    X = np.asarray(vectors, dtype=float)
    X = X[:, :min(8, X.shape[1])]  # 统一维度
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    _, _, vt = np.linalg.svd(X - X.mean(0), full_matrices=False)
    coords = (X - X.mean(0)) @ vt[:3].T
    while coords.shape[1] < 3:
        coords = np.hstack([coords, np.zeros((len(coords), 1))])

    fig = go.Figure()
    for grp, color, size in (("其他用户", "#3B82F6", 7), ("我", "#EF4444", 13)):
        idx = [i for i, g in enumerate(groups) if g == grp]
        if not idx:
            continue
        fig.add_trace(go.Scatter3d(
            x=coords[idx, 0], y=coords[idx, 1], z=coords[idx, 2],
            mode="markers+text", name=grp,
            marker=dict(size=size, color=color, opacity=0.85),
            text=[labels[i] for i in idx], textposition="top center",
            textfont=dict(size=11),
        ))
    fig.update_layout(
        title=dict(text="用户画像超几何空间 · 相似者聚簇（PCA 三维投影）", x=0.5),
        scene=dict(xaxis_title="主成分 1", yaxis_title="主成分 2", zaxis_title="主成分 3",
                   bgcolor="#F8FAFC"),
        width=1100, height=750, margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(x=0.02, y=0.98),
    )
    fig.write_html(out, include_plotlyjs="cdn")
    return out


# ---------------- GUI ----------------

def main():
    global _ROOT
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import auth
    import mydata
    import db
    db.init_db()  # 本地 SQLite 建表（便携版首次运行没有 app.py 兜底，必须自建）

    root = tk.Tk()
    _ROOT = root
    root.title(APP_TITLE)
    root.geometry("980x700")
    root.minsize(860, 600)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    status_var = tk.StringVar(value="就绪")
    user_var = tk.StringVar(value="")

    # ---------- 登录/注册页 ----------
    auth_frame = ttk.Frame(root, padding=60)

    ttk.Label(auth_frame, text=APP_TITLE, font=("", 18, "bold")).pack(pady=(0, 24))
    form = ttk.Frame(auth_frame)
    form.pack()
    ttk.Label(form, text="用户名", width=10).grid(row=0, column=0, pady=6, sticky="e")
    ttk.Label(form, text="密码", width=10).grid(row=1, column=0, pady=6, sticky="e")
    ttk.Label(form, text="确认密码", width=10).grid(row=2, column=0, pady=6, sticky="e")
    name_e = ttk.Entry(form, width=28)
    pw_e = ttk.Entry(form, width=28, show="•")
    pw2_e = ttk.Entry(form, width=28, show="•")
    name_e.grid(row=0, column=1)
    pw_e.grid(row=1, column=1)
    pw2_e.grid(row=2, column=1)
    msg_var = tk.StringVar(value="")
    ttk.Label(auth_frame, textvariable=msg_var, foreground="#DC2626").pack(pady=(8, 0))

    mode_var = tk.StringVar(value="login")

    def _submit():
        u, p1, p2 = name_e.get(), pw_e.get(), pw2_e.get()
        msg_var.set("")
        if mode_var.get() == "register" and p1 != p2:
            msg_var.set("两次输入的密码不一致")
            return

        def work():
            if mode_var.get() == "register":
                return auth.register(u, p1)
            return auth.login(u, p1)

        def done(ok, res):
            if not ok:
                msg_var.set("连接服务器失败：%s" % res)
                return
            success, message = res
            if success:
                user_var.set(auth.current_user() or "")
                show_main()
            else:
                msg_var.set(message)
        status_var.set("连接服务器…")
        _bg(work, done)

    btns = ttk.Frame(auth_frame)
    btns.pack(pady=18)
    ttk.Button(btns, text="登 录", width=12, command=lambda: (mode_var.set("login"), _submit())).grid(row=0, column=0, padx=8)
    ttk.Button(btns, text="注册新账号", width=12, command=lambda: (mode_var.set("register"), _submit())).grid(row=0, column=1, padx=8)

    def try_auto_login():
        status_var.set("连接服务器…")

        def work():
            u = auth.current_user()
            s = mydata.pool_stats() if u else None
            return u, s

        def done(ok, res):
            if not ok:
                status_var.set("云数据库连接失败：%s" % res)
                return
            u, s = res
            if u:
                user_var.set(u)
                show_main()
            else:
                status_var.set("就绪（未登录）")
        _bg(work, done)

    # ---------- 主界面 ----------
    main_frame = ttk.Frame(root)
    main_built = [False]

    def show_main():
        auth_frame.pack_forget()
        main_frame.pack(fill="both", expand=True)
        if main_built[0]:  # 登录/自动登录/重复回调都只构建一次，避免界面堆叠
            status_var.set("就绪")
            return
        main_built[0] = True
        try:
            top = ttk.Frame(main_frame, padding=(10, 6))
            top.pack(fill="x")
            ttk.Label(top, textvariable=user_var, font=("", 11, "bold")).pack(side="left")
            ttk.Label(top, text="   登录中").pack(side="left")

            def do_logout():
                auth.logout()
                main_frame.pack_forget()
                auth_frame.pack(expand=True)
                status_var.set("已退出登录")
            ttk.Button(top, text="退出登录", command=do_logout).pack(side="right")

            nb = ttk.Notebook(main_frame)
            nb.pack(fill="both", expand=True, padx=8, pady=4)
            build_resume_tab(nb)
            build_delivery_tab(nb)
            build_plaza_tab(nb)
            build_jobs_tab(nb)
            status_var.set("就绪")
        except Exception as exc:
            status_var.set("界面加载失败：%s" % exc)
            messagebox.showerror("界面加载失败", str(exc))

    # ----- Tab1 简历信息 -----
    def build_resume_tab(nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 我的简历 ")
        bar = ttk.Frame(tab)          # 容器先占位在顶部
        bar.pack(fill="x", pady=(0, 8))

        canvas = tk.Canvas(tab, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        import schema
        entries = {}
        ttk.Label(inner, text="基本信息（L0）", font=("", 11, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(4, 6))
        for i, f in enumerate(schema.L0_FIELDS):
            ttk.Label(inner, text=f, width=10).grid(row=1 + i // 2, column=(i % 2) * 2, sticky="e", pady=3)
            e = ttk.Entry(inner, width=32)
            e.grid(row=1 + i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=4)
            entries[f] = e

        row = 1 + (len(schema.L0_FIELDS) + 1) // 2 + 1
        ttk.Label(inner, text="意向岗位", font=("", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(10, 4))
        intent_e = ttk.Entry(inner, width=60)
        intent_e.grid(row=row, column=1, columnspan=3, sticky="w", pady=4)

        row += 1
        ttk.Label(inner, text="经历（L2，JSON 明细）", font=("", 11, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(10, 4))
        row += 1
        exp_text = tk.Text(inner, width=100, height=14, font=("Consolas", 10))
        exp_text.grid(row=row, column=0, columnspan=4, sticky="w")

        def fill(parsed):
            for f, e in entries.items():
                e.delete(0, "end")
                v = parsed.get(f, "")
                if v:
                    e.insert(0, str(v))
            intent_e.delete(0, "end")
            if parsed.get("意向岗位"):
                intent_e.insert(0, str(parsed["意向岗位"]))
            exp_text.delete("1.0", "end")
            exps = parsed.get("经历", []) or []
            if exps:
                exp_text.insert("1.0", json.dumps(exps, ensure_ascii=False, indent=1))

        def collect():
            parsed = {f: e.get().strip() for f, e in entries.items() if e.get().strip()}
            if intent_e.get().strip():
                parsed["意向岗位"] = intent_e.get().strip()
            raw = exp_text.get("1.0", "end").strip()
            if raw:
                try:
                    exps = json.loads(raw)
                    if isinstance(exps, list):
                        parsed["经历"] = exps
                except ValueError:
                    pass
            return parsed

        def import_pdf():
            path = filedialog.askopenfilename(title="选择简历 PDF", filetypes=[("PDF", "*.pdf")])
            if not path:
                return
            status_var.set("解析中（规则 + DeepSeek AI）…")

            def work():
                import pdfplumber
                import resume_ai
                with pdfplumber.open(path) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                return resume_ai.smart_parse(text)

            def done(ok, res):
                if not ok:
                    messagebox.showerror("解析失败", str(res))
                    status_var.set("解析失败")
                    return
                if not res:
                    messagebox.showwarning("未识别", "未能从该 PDF 提取有效信息")
                    status_var.set("未识别")
                    return
                fill(res)
                n_exp = len(res.get("经历", []) or [])
                status_var.set("AI 解析完成：经历 %d 段，检查后点「保存到云端」" % n_exp)
            _bg(work, done)

        def load_local():
            status_var.set("从本地库载入…")

            def work():
                import pipeline
                r = pipeline.latest_user_data()
                if r is None:
                    return None
                out = dict(r["l0"])
                if r["l3"].get("意向岗位"):
                    out["意向岗位"] = r["l3"]["意向岗位"]
                out["经历"] = r["l2"]
                return out

            def done(ok, res):
                if not ok:
                    messagebox.showerror("载入失败", str(res))
                    return
                if res is None:
                    status_var.set("本地库还没有简历，先导入或填写后保存")
                    return
                fill(res)
                status_var.set("已从本地库载入")
            _bg(work, done)

        def save_local():
            parsed = collect()
            if not parsed:
                messagebox.showwarning("空内容", "没有可保存的内容")
                return
            status_var.set("保存到本地库…")

            def work():
                import pipeline
                exps = parsed.get("经历", []) or []
                l1 = {}
                for it in exps:
                    t = (it.get("类型") or "其他") if isinstance(it, dict) else "其他"
                    l1[t] = l1.get(t, 0) + 1
                l0 = {f: parsed[f] for f in schema.L0_FIELDS if f in parsed}
                l3 = {"意向岗位": parsed.get("意向岗位", ""),
                      "意向城市": l0.get("现居", "")}
                return pipeline.store_user({"l0": l0, "l1": l1, "l2": exps, "l3": l3})

            def done(ok, res):
                if not ok:
                    messagebox.showerror("保存失败", str(res))
                    return
                status_var.set("已保存到本地库（投递工作台将使用这份简历）")
            _bg(work, done)

        def clear_form():
            fill({})
            status_var.set("已清空表单（不影响本地库数据）")

        # 工具栏按钮放在所有回调定义之后（tkinter command 构建时就要解析到函数对象）
        ttk.Button(bar, text="📄 导入 PDF 简历（AI 解析）",
                   command=import_pdf).pack(side="left", padx=2)
        ttk.Button(bar, text="📂 从本地库载入", command=load_local).pack(side="left", padx=2)
        ttk.Button(bar, text="💾 保存到本地库", command=save_local).pack(side="left", padx=2)
        ttk.Button(bar, text="清空", command=clear_form).pack(side="left", padx=2)
        tab.lift()

    # ----- Tab2 投递工作台 -----
    def build_delivery_tab(nb):
        import flow
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 投递工作台 ")

        scene = {"user_id": None, "jobs": []}   # 本次会话的现场
        plat_state_vars = {}                     # key -> StringVar

        # —— 顶栏：安全模式 ——
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 6))
        safe_var = tk.BooleanVar(value=bool(config.SAFE_MODE))

        def toggle_safe():
            config.SAFE_MODE = bool(safe_var.get())
            status_var.set("安全模式已%s（%s）" %
                           ("开启：只演练不真投" if config.SAFE_MODE else "关闭：将真实投递，封号风险自负",
                            "推荐保持开启" if config.SAFE_MODE else "请谨慎"))
        ttk.Checkbutton(top, text="安全模式（只演练不真投，推荐开启）",
                        variable=safe_var, command=toggle_safe).pack(side="left")

        # —— ① 平台登录态 ——
        plat_box = ttk.LabelFrame(tab, text="① 平台登录（真实浏览器扫码/输密码，登录后点「完成登录」保存会话）")
        plat_box.pack(fill="x", pady=4)

        def refresh_states():
            def work():
                return flow.login_states(online=False)
            def done(ok, res):
                if not ok:
                    status_var.set("登录态检测失败：%s" % res)
                    return
                logged = []
                for k, st in res.items():
                    if k in plat_state_vars:
                        plat_state_vars[k].set("%s｜%s" % (st["state"], st["detail"] or "-"))
                    if st["state"] == "saved":
                        logged.append(k)
                status_var.set("登录态已刷新，可检索平台：%s" % ("、".join(logged) or "无（先登录）"))
            _bg(work, done)

        for i, p in enumerate(flow.available_platforms()):
            row = ttk.Frame(plat_box)
            row.grid(row=i // 2, column=i % 2, sticky="w", padx=10, pady=3)
            ttk.Label(row, text=p["name"] + ("（测试）" if p["key"] == "mock" else ""),
                      width=14).pack(side="left")
            sv = tk.StringVar(value="未检测")
            plat_state_vars[p["key"]] = sv
            ttk.Label(row, textvariable=sv, width=26, foreground="#2563EB").pack(side="left")

            def make_login(k):
                def do_login():
                    status_var.set("已打开 %s 登录窗口，完成扫码/登录后回来点「完成登录」" % k)
                    def work():
                        flow.start_login(k)
                        return k
                    def done(ok, res):
                        if not ok:
                            messagebox.showerror("打开登录失败", str(res))
                    _bg(work, done)
                return do_login

            def make_finish(k):
                def do_finish():
                    def work():
                        return flow.finish_login(k)
                    def done(ok, res):
                        if not ok:
                            messagebox.showerror("保存会话失败", str(res))
                            return
                        ok2, state = res
                        plat_state_vars[k].set("%s｜会话已保存" % state)
                        status_var.set("%s 登录态：%s" % (k, state))
                        refresh_states()
                    _bg(work, done)
                return do_finish

            ttk.Button(row, text="登录", width=6,
                       command=make_login(p["key"])).pack(side="left", padx=2)
            ttk.Button(row, text="完成登录", width=8,
                       command=make_finish(p["key"])).pack(side="left", padx=2)
        ttk.Button(plat_box, text="刷新登录态", command=refresh_states).grid(
            row=(len(flow.available_platforms()) + 1) // 2, column=0, sticky="w", padx=10, pady=4)

        # —— ② 检索 + 全流程 ——
        op_box = ttk.LabelFrame(tab, text="② 检索 → 匹配建任务 → 生成材料（全程本地库，不依赖云端）")
        op_box.pack(fill="x", pady=4)
        ttk.Label(op_box, text="关键词").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        kw_e = ttk.Entry(op_box, width=24)
        kw_e.grid(row=0, column=1, sticky="w")
        kw_e.insert(0, "后端")
        ttk.Label(op_box, text="页数").grid(row=0, column=2, padx=6, sticky="e")
        pages_sp = tk.Spinbox(op_box, from_=1, to=10, width=5)
        pages_sp.grid(row=0, column=3, sticky="w")
        pages_sp.delete(0, "end")
        pages_sp.insert(0, "2")
        search_var = tk.StringVar(value="尚未检索")

        def _current_user_data():
            import pipeline
            u = pipeline.latest_user_data()
            if u is None:
                raise RuntimeError("本地库没有简历，请先在「我的简历」页保存")
            return u

        def _logged_keys(states):
            return [k for k, st in states.items() if st["state"] == "saved"]

        def do_search():
            status_var.set("检索岗位中…")
            def work():
                states = flow.login_states(online=False)
                keys = _logged_keys(states)
                if not keys:
                    raise RuntimeError("没有已登录平台，请先在①登录")
                u = _current_user_data()
                jobs, logs = flow.search(u, keys, kw_e.get().strip() or "后端",
                                         pages=int(pages_sp.get()))
                return jobs, logs, keys
            def done(ok, res):
                if not ok:
                    messagebox.showerror("检索失败", str(res))
                    status_var.set("检索失败")
                    return
                jobs, logs, keys = res
                scene["jobs"] = jobs
                search_var.set("已检索 %d 个岗位（平台：%s）" % (len(jobs), "、".join(keys)))
                status_var.set("检索完成：%d 个岗位，下一步点「匹配并生成材料」" % len(jobs))
            _bg(work, done)
        ttk.Button(op_box, text="🔍 检索岗位", command=do_search).grid(row=0, column=4, padx=8)
        ttk.Label(op_box, textvariable=search_var, foreground="#2563EB").grid(
            row=0, column=5, padx=8, sticky="w")

        def do_pipeline():
            if not scene["jobs"]:
                messagebox.showwarning("没有岗位", "请先检索岗位")
                return
            status_var.set("核检 → 画像 → 匹配 → 建任务 → 生成材料…")
            def work():
                u = _current_user_data()
                return flow.run_pipeline(u, scene["jobs"])
            def done(ok, res):
                if not ok:
                    messagebox.showerror("全流程失败", str(res))
                    status_var.set("全流程失败")
                    return
                if not res.get("ok"):
                    messagebox.showwarning("全流程未通过", str(res.get("error") or res))
                    return
                scene["user_id"] = res["user_id"]
                refresh_tasks()
                status_var.set("全流程完成：%d 个任务已生成材料" % res["task_count"])
            _bg(work, done)
        ttk.Button(op_box, text="⚙ 匹配并生成材料", command=do_pipeline).grid(row=1, column=4, padx=8, pady=4)

        # —— ③ 任务表 ——
        task_box = ttk.LabelFrame(tab, text="③ 投递任务（按匹配分排序，重启后可点「恢复上次现场」）")
        task_box.pack(fill="both", expand=True, pady=4)
        cols = ("tid", "job", "unit", "score", "status", "result")
        tree = ttk.Treeview(task_box, columns=cols, show="headings")
        for c, t, w in (("tid", "任务号", 60), ("job", "岗位名称", 240), ("unit", "单位", 170),
                        ("score", "匹配分", 70), ("status", "状态", 90), ("result", "结果", 110)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w" if c in ("job", "unit") else "center")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(task_box, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<Double-1>", lambda e: preview_task())

        def _selected_tid():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("未选择", "先在任务表中选中一行")
                return None
            return int(tree.item(sel[0], "values")[0])

        def refresh_tasks():
            for i in tree.get_children():
                tree.delete(i)
            uid = scene["user_id"]
            if uid is None:
                return
            for t in flow.list_tasks(uid):
                tree.insert("", "end", values=(
                    t.get("task_id"), t.get("job_name") or "", t.get("unit_name") or "",
                    "%.3f" % (t.get("match_score") or 0),
                    t.get("status") or "", t.get("result") or ""))

        def restore_scene():
            status_var.set("恢复上次现场…")
            def work():
                return flow.restore_scene()
            def done(ok, res):
                if not ok:
                    messagebox.showerror("恢复失败", str(res))
                    return
                if not res:
                    status_var.set("本地库没有历史投递现场")
                    return
                scene["user_id"] = res["user_id"]
                scene["jobs"] = []
                refresh_tasks()
                status_var.set("已恢复上次现场：%d 个任务" % res["task_count"])
            _bg(work, done)

        def preview_task():
            tid = _selected_tid()
            if tid is None:
                return
            d = flow.task_detail(tid)
            if not d:
                messagebox.showwarning("无详情", "任务 #%d 不存在" % tid)
                return
            win = tk.Toplevel(tab)
            win.title("任务 #%d 材料预览" % tid)
            win.geometry("640x520")
            txt = tk.Text(win, wrap="word", font=("Consolas", 10))
            txt.pack(fill="both", expand=True, padx=8, pady=8)
            txt.insert("1.0", "岗位：%s @ %s\n状态：%s\n\n【招呼语】\n%s\n\n【针对性简历字段】\n%s" % (
                d.get("job_name", ""), d.get("unit_name", ""), d.get("status", ""),
                d.get("招呼语") or "-", json.dumps(d.get("简历内容") or {}, ensure_ascii=False, indent=1)))

        def deliver_selected():
            tid = _selected_tid()
            if tid is None:
                return
            status_var.set("任务 #%d 投递中（安全模式=%s）…" % (tid, config.SAFE_MODE))
            def work():
                return flow.deliver_one(tid)
            def done(ok, res):
                if not ok:
                    messagebox.showerror("投递失败", str(res))
                    return
                ok2, material = res
                refresh_tasks()
                if ok2 and material:
                    win = tk.Toplevel(tab)
                    win.title("任务 #%d 投递材料（安全模式预览，未真实发送）" % tid)
                    win.geometry("560x420")
                    txt = tk.Text(win, wrap="word", font=("Consolas", 10))
                    txt.pack(fill="both", expand=True, padx=8, pady=8)
                    txt.insert("1.0", str(material))
                else:
                    messagebox.showinfo("投递", str(material or "已处理"))
                status_var.set("任务 #%d 投递完成" % tid)
            _bg(work, done)

        def manual_selected():
            tid = _selected_tid()
            if tid is None:
                return
            if not messagebox.askyesno("确认手动投递", "确认你已在平台上手动完成 #%d 的投递？" % tid):
                return
            def work():
                return flow.confirm_manual(tid)
            def done(ok, res):
                if not ok:
                    messagebox.showerror("记录失败", str(res))
                    return
                ok2, msg = res
                refresh_tasks()
                status_var.set(msg)
            _bg(work, done)

        def batch_deliver():
            if not messagebox.askyesno("批量投递", "对全部待投递任务执行批量投递？\n安全模式=%s" % config.SAFE_MODE):
                return
            status_var.set("批量投递中（防封间隔生效，请耐心等待）…")
            def work():
                return flow.deliver_batch(all_pending=True)
            def done(ok, res):
                if not ok:
                    messagebox.showerror("批量投递失败", str(res))
                    return
                refresh_tasks()
                messagebox.showinfo("批量投递结果",
                                    "成功 %d / 失败 %d\n停止原因：%s" % (
                                        res.get("成功数", 0), res.get("失败数", 0),
                                        res.get("停止原因") or "无"))
                status_var.set("批量投递完成")
            _bg(work, done)

        fb_var = tk.StringVar(value="进面试")

        def mark_fb():
            tid = _selected_tid()
            if tid is None:
                return
            val = 1 if fb_var.get() == "进面试" else 0
            def work():
                return flow.mark_feedback(tid, val)
            def done(ok, res):
                if not ok:
                    messagebox.showerror("反馈失败", str(res))
                    return
                if not res.get("ok"):
                    messagebox.showwarning("反馈未生效", res.get("msg") or "")
                    return
                refresh_tasks()
                st = res.get("stats") or {}
                status_var.set("反馈已回写（式五权重更新）：累计投递 %s，进面试 %s" % (
                    st.get("累计投递", "-"), st.get("进面试", "-")))
            _bg(work, done)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="⟲ 恢复上次现场", command=restore_scene).pack(side="left", padx=2)
        ttk.Button(btns, text="👁 预览材料", command=preview_task).pack(side="left", padx=2)
        ttk.Button(btns, text="📮 投递此条", command=deliver_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="✍ 确认手动投递", command=manual_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="📮📮 批量投递全部", command=batch_deliver).pack(side="left", padx=2)
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(btns, text="结果反馈：").pack(side="left")
        ttk.Combobox(btns, textvariable=fb_var, values=("进面试", "未通过/无回复"),
                     width=14, state="readonly").pack(side="left")
        ttk.Button(btns, text="回写反馈", command=mark_fb).pack(side="left", padx=4)

        refresh_states()

    # ----- Tab3 画像对比 -----
    def build_plaza_tab(nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 画像对比 ")
        info_var = tk.StringVar(value="")
        ttk.Label(tab, text="把公开画像投放到超几何空间：相似的人聚成一簇，位置越近画像越像。",
                  font=("", 10)).pack(anchor="w", pady=4)
        ttk.Label(tab, textvariable=info_var, foreground="#2563EB").pack(anchor="w", pady=2)

        def refresh_info():
            def work():
                return mydata.pool_stats(), len(mydata.list_public_profiles(exclude_owner=None))
            def done(ok, res):
                if ok:
                    s, pub = res
                    info_var.set("云库状态：注册账号 %d 个 | 共享岗位 %d 个 | 公开画像 %d 份"
                                 % (s["accounts"], s["jobs"], pub))
            _bg(work, done)
        ttk.Button(tab, text="刷新统计", command=refresh_info).pack(anchor="w", pady=4)

        def gen_chart():
            status_var.set("生成对比图…")

            def work():
                return build_compare_chart(user_var.get())

            def done(ok, res):
                if not ok:
                    messagebox.showerror("生成失败", str(res))
                    return
                webbrowser.open("file://" + res)
                status_var.set("已生成并在浏览器打开：%s" % res)
            _bg(work, done)
        ttk.Button(tab, text="🧭 生成我的画像空间图（浏览器打开）",
                   command=gen_chart).pack(anchor="w", pady=6)

        ttk.Separator(tab).pack(fill="x", pady=10)
        ttk.Label(tab, text="我的画像快照可见性", font=("", 10, "bold")).pack(anchor="w")
        list_frame = ttk.Frame(tab)
        list_frame.pack(fill="both", expand=True, pady=4)
        cols = ("snap", "vis", "ts", "delivered", "interview")
        tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8)
        for c, t, w in (("snap", "快照ID", 70), ("vis", "可见性", 90), ("ts", "时间", 160),
                        ("delivered", "投递数", 70), ("interview", "进面试", 70)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview).pack(side="right", fill="y")
        tree.configure(yscrollcommand=tree.yview)

        def refresh_snaps():
            for i in tree.get_children():
                tree.delete(i)
            for r in mydata.list_my_profiles(user_var.get()):
                g = lambda k, i: (r[k] if isinstance(r, dict) else r[i])
                tree.insert("", "end", values=(g("snap_id", 0), g("visibility", 1), g("ts", 2),
                                               g("delivered_count", 3), g("interview_count", 4)))
        ttk.Button(tab, text="刷新我的快照列表", command=refresh_snaps).pack(anchor="w", pady=2)
        ttk.Label(tab, text="提示：可见性 public = 作为对比数据对其他用户可见；在网页端完成投递闭环会自动产生快照。",
                  foreground="#666").pack(anchor="w", pady=4)

    # ----- Tab4 共享岗位池 -----
    def build_jobs_tab(nb):
        import cloud_sync
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 共享岗位池 ")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 6))
        pool_var = tk.StringVar(value="")

        def refresh():
            status_var.set("拉取岗位池…")

            def work():
                return mydata.list_jobs(500), cloud_sync.pool_counts()

            def done(ok, res):
                if not ok:
                    messagebox.showerror("拉取失败", str(res))
                    return
                jobs, counts = res
                for i in tree.get_children():
                    tree.delete(i)
                for j in jobs:
                    tree.insert("", "end", values=(
                        j.get("岗位名称", ""), j.get("单位名称", ""), j.get("城市", ""),
                        j.get("薪资", ""), j.get("经验", ""), j.get("学历", "")))
                pool_var.set("两端岗位数 —— 本地：%d ｜ 云端共享池：%d" % (counts["本地"], counts["云端"]))
                status_var.set("岗位池已刷新：%d 条（全队共享）" % len(jobs))
            _bg(work, done)

        def push_pool():
            if not messagebox.askyesno("推送岗位池", "把本地岗位去重后推送到云端共享池？\n提交者标识：%s" % user_var.get()):
                return
            status_var.set("推送本地岗位到云端…")
            def work():
                return cloud_sync.push_jobs(user_var.get() or "anonymous")
            def done(ok, res):
                if not ok:
                    messagebox.showerror("推送失败", str(res))
                    return
                messagebox.showinfo("推送完成", "新增 %d 条｜云端已有 %d 条｜本地共 %d 条" % (
                    res["新增"], res["云端已有"], res["本地岗位数"]))
                status_var.set("岗位池推送完成")
            _bg(work, done)

        def pull_pool():
            status_var.set("从云端拉取新岗位…")
            def work():
                return cloud_sync.pull_jobs()
            def done(ok, res):
                if not ok:
                    messagebox.showerror("拉取失败", str(res))
                    return
                status_var.set("已拉回 %d 个新岗位到本地库（供检索匹配使用）" % res["拉回"])
            _bg(work, done)

        ttk.Button(top, text="🔄 刷新岗位池", command=refresh).pack(side="left", padx=2)
        ttk.Button(top, text="⬆ 推送本地岗位到云端", command=push_pool).pack(side="left", padx=2)
        ttk.Button(top, text="⬇ 从云端拉取新岗位", command=pull_pool).pack(side="left", padx=2)
        ttk.Label(top, textvariable=pool_var, foreground="#2563EB").pack(side="left", padx=10)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        cols = ("name", "unit", "city", "salary", "exp", "edu")
        tree = ttk.Treeview(body, columns=cols, show="headings")
        for c, t, w in (("name", "岗位名称", 240), ("unit", "单位", 180), ("city", "城市", 80),
                        ("salary", "薪资", 110), ("exp", "经验", 90), ("edu", "学历", 80)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

    # ---------- 状态栏 ----------
    ttk.Separator(root, orient="horizontal").pack(fill="x", side="bottom")
    ttk.Label(root, textvariable=status_var, padding=(10, 4)).pack(fill="x", side="bottom")

    auth_frame.pack(expand=True)
    if os.environ.get("JOBDELIVERY_GUI_TEST"):
        root.after(8000, root.destroy)  # 测试模式：走完整流程后自动关闭
    try_auto_login()
    root.mainloop()


if __name__ == "__main__":
    main()

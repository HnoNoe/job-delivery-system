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

    def show_main():
        auth_frame.pack_forget()
        main_frame.pack(fill="both", expand=True)
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
        build_plaza_tab(nb)
        build_jobs_tab(nb)
        status_var.set("就绪")

    # ----- Tab1 简历信息 -----
    def build_resume_tab(nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 我的简历 ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="📄 导入 PDF 简历（AI 解析）",
                   command=import_pdf).pack(side="left", padx=2)
        ttk.Button(bar, text="☁ 从云端载入", command=load_cloud).pack(side="left", padx=2)
        ttk.Button(bar, text="💾 保存到云端", command=save_cloud).pack(side="left", padx=2)
        ttk.Button(bar, text="清空", command=clear_form).pack(side="left", padx=2)

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

        def load_cloud():
            status_var.set("从云端载入…")

            def work():
                r = mydata.load_resume(user_var.get())
                if r is None:
                    return None
                out = dict(r["l0"])
                if r["l3"].get("意向岗位"):
                    out["意向岗位"] = r["l3"]["意向岗位"]
                out["经历"] = r["experiences"]
                return out

            def done(ok, res):
                if not ok:
                    messagebox.showerror("载入失败", str(res))
                    return
                if res is None:
                    status_var.set("云端还没有你的简历，先导入或填写")
                    return
                fill(res)
                status_var.set("已从云端载入")
            _bg(work, done)

        def save_cloud():
            parsed = collect()
            if not parsed:
                messagebox.showwarning("空内容", "没有可保存的内容")
                return
            status_var.set("保存到云端…")

            def work():
                return mydata.save_resume(user_var.get(), parsed)

            def done(ok, res):
                if not ok:
                    messagebox.showerror("保存失败", str(res))
                    return
                status_var.set("已保存（简历仅本人账号可见）")
            _bg(work, done)

        def clear_form():
            fill({})
            status_var.set("已清空表单（不影响云端数据）")

    # ----- Tab2 画像对比 -----
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

    # ----- Tab3 岗位池 -----
    def build_jobs_tab(nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text=" 共享岗位池 ")
        cols = ("name", "unit", "city", "salary", "exp", "edu")
        tree = ttk.Treeview(tab, columns=cols, show="headings")
        for c, t, w in (("name", "岗位名称", 240), ("unit", "单位", 180), ("city", "城市", 80),
                        ("salary", "薪资", 110), ("exp", "经验", 90), ("edu", "学历", 80)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        def refresh():
            status_var.set("拉取岗位池…")

            def work():
                return mydata.list_jobs(500)

            def done(ok, res):
                if not ok:
                    messagebox.showerror("拉取失败", str(res))
                    return
                for i in tree.get_children():
                    tree.delete(i)
                for j in res:
                    tree.insert("", "end", values=(
                        j.get("岗位名称", ""), j.get("单位名称", ""), j.get("城市", ""),
                        j.get("薪资", ""), j.get("经验", ""), j.get("学历", "")))
                status_var.set("岗位池已刷新：%d 条（全队共享）" % len(res))
            _bg(work, done)
        ttk.Button(tab, text="🔄 刷新岗位池", command=refresh).pack(anchor="w", pady=(8, 0))

    # ---------- 状态栏 ----------
    ttk.Separator(root, orient="horizontal").pack(fill="x", side="bottom")
    ttk.Label(root, textvariable=status_var, padding=(10, 4)).pack(fill="x", side="bottom")

    auth_frame.pack(expand=True)
    if os.environ.get("JOBDELIVERY_GUI_TEST"):
        root.after(1200, root.destroy)
    else:
        try_auto_login()
    root.mainloop()


if __name__ == "__main__":
    main()

"""设计验证脚本（临时）：截图新主题的落地页 + 图表模板效果。

流程：启动 Streamlit(8502) → DrissionPage 无头截图落地页 →
真实 pipeline 造数据渲染关键图表为 HTML → 截图 → 关闭一切。
运行后自动生成 preview_landing.png / preview_charts.png，进程全部退出。
"""
import subprocess
import sys
import time
import urllib.request

PORT = 8502
BASE = f"http://127.0.0.1:{PORT}"


def wait_http(url, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(url, timeout=2).status == 200:
                return True
        except Exception:
            time.sleep(1)
    return False


def shot(url, path, height=1400, wait=6):
    from DrissionPage import ChromiumPage, ChromiumOptions
    co = ChromiumOptions().headless()
    co.auto_port()  # 独立调试端口+临时用户目录，避免与用户已开 Chrome 冲突
    co.set_argument("--window-size", f"1440,{height}")
    co.set_argument("--force-device-scale-factor", "1")
    page = ChromiumPage(co)
    try:
        page.get(url)
        time.sleep(wait)
        page.get_screenshot(path=path, full_page=True)
        print("saved:", path)
    finally:
        page.quit()


def build_charts_html(html_path):
    """跑一次真实 pipeline，用 viz.py（与 app.py 完全同源）构造图表，导出 HTML。"""
    import config, pipeline, theme, viz

    config.SAFE_MODE = True
    user_data = {
        "l0": {"姓名": "张三", "性别": "男", "出生日期": "2001-05-06", "手机": "13912345678",
               "邮箱": "a@b.com", "政治面貌": "共青团员", "民族": "汉族", "现居": "北京",
               "籍贯": "江苏", "学历阶段": "本科在读", "学校": "北京理工大学", "学院": "计算机学院",
               "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
        "l1": {"实习/工作": 1, "项目": 1},
        "l2": [
            {"类型": "实习/工作", "名称": "Python后端实习生", "角色": "实习生", "时间起": "2023-06",
             "时间止": "2023-09", "事项": "接口开发 Flask+MySQL", "结果": "提升30%",
             "技术工具": "Python, Flask, MySQL", "挂靠": "独立", "证据": "无"},
            {"类型": "项目", "名称": "电商秒杀", "角色": "负责人", "时间起": "2023-01",
             "时间止": "2023-05", "事项": "Spring Boot 秒杀", "结果": "QPS1000",
             "技术工具": "Java, Spring, Redis", "挂靠": "独立", "证据": "无"},
        ],
        "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发",
               "到岗时间": "2024-07", "期望薪资": "15k/月", "投递策略": "海投", "能否出差": "是"},
    }
    jobs = [
        {"岗位名称": "Python后端开发工程师", "单位名称": "示例科技", "岗位链接": "https://e.com/1",
         "城市": "北京", "行业": "互联网", "公司": "示例科技", "薪资": "15k/月", "学历": "本科",
         "经验": "不限", "技能": "python,flask,mysql,后端", "已沟通": False, "岗位描述": "后端"},
        {"岗位名称": "前端开发工程师", "单位名称": "前端科技", "岗位链接": "https://e.com/2",
         "城市": "北京", "行业": "互联网", "公司": "前端科技", "薪资": "14k/月", "学历": "本科",
         "经验": "不限", "技能": "vue,javascript,前端", "已沟通": False, "岗位描述": "前端"},
        {"岗位名称": "算法工程师", "单位名称": "智能科技", "岗位链接": "https://e.com/3",
         "城市": "北京", "行业": "人工智能", "公司": "智能科技", "薪资": "20k/月", "学历": "硕士",
         "经验": "不限", "技能": "python,机器学习,深度学习", "已沟通": False, "岗位描述": "算法"},
    ]
    r = pipeline.run_full_pipeline(user_data, jobs=jobs)
    targets = r["target_jobs"]
    top = targets[0] if targets else None
    figs = [f for f in [
        viz.grade_donut(targets),
        viz.score_bar(targets),
        viz.six_dim_radar(top) if top else None,
        viz.six_dim_bars(top) if top else None,
        viz.delivery_funnel(30, len(targets), 2, 1),
        viz.stacked_dims(targets),
        viz.skill_coverage(targets, user_data["l2"])[0],
    ] if f is not None]

    _H = [380, 380, 380, 380, 340, 400]
    parts = []
    for i, f in enumerate(figs):
        f.update_layout(height=_H[i] if i < len(_H) else 380)
        parts.append(f.to_html(full_html=False, include_plotlyjs=True if i == 0 else False,
                               config={"responsive": False, "displayModeBar": False}))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write('<meta charset="utf-8"><body style="background:%s;margin:0;'
                'padding:24px;font-family:sans-serif">'
                '<div style="max-width:1100px;margin:auto;background:#fff;'
                'border-radius:16px;padding:16px">%s</div></body>'
                % (theme.PAPER, "".join(parts)))
    print("saved:", html_path)


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT), "--server.headless", "true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_http(BASE):
            print("streamlit failed to start")
            return 1
        shot(BASE, "preview_landing.png", height=2400, wait=8)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    build_charts_html("preview_charts.html")
    shot("file:///" + __import__("os").path.abspath("preview_charts.html").replace("\\", "/"),
         "preview_charts.png", height=2600, wait=5)
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

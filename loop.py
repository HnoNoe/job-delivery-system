"""闭环编排器：把七步 + 反馈轮询 + 权重修正串成完整闭环。

闭环：登录 → 检索 → 画像 → 匹配 → 建任务 → 生成简历 → 投递 → 轮询反馈 → 权重修正 → 再画像。
每一步输出是下一步输入，投递反馈回流修正画像，形成数据闭环。
"""
import db
import session
import crawler
import platforms
import pipeline
import feedback
from logging_setup import get_logger

log = get_logger(__name__)


def search_logged_in_platforms(platform_keys, keyword, city="", pages=1):
    """在已登录平台检索。真实平台用 DrissionPage 旁听接口（会自己用持久化 profile 重开浏览器）。"""
    jobs, logs = [], []
    for k in platform_keys or []:
        p = platforms.get(k)
        if not p.get("api_field_map"):
            logs.append((k, "该平台暂未适配检索（缺接口字段映射）"))
            continue
        if session.is_active(k):
            got = session.dpage_search(k, keyword, city=city, pages=pages)
        else:
            logs.append((k, "未登录，跳过"))
            continue
        jobs.extend(got)
        if got:
            logs.append((k, "检索到 %d 个岗位" % len(got)))
        else:
            logs.append((k, "检索到 0 个岗位（登录态可能失效，请回到第②步重新扫码登录）"))
    return jobs, logs


def run_closed_loop(user_data, platform_keys=None, keyword="", jobs=None, llm=None):
    """执行完整闭环（不自动投递、不伪造反馈）。"""
    log.info("闭环启动：platforms=%s keyword=%s", platform_keys, keyword)

    # ① 检索
    if jobs is None and platform_keys:
        jobs, search_logs = search_logged_in_platforms(platform_keys, keyword)
    else:
        search_logs = []

    # ②-⑥ 画像→匹配→建任务→生成→准备投递材料
    result = pipeline.run_full_pipeline(user_data, llm=llm, jobs=jobs)
    if not result["ok"]:
        log.warning("闭环中止：核检未通过 %s", result["errors"])
        return result

    result["search_logs"] = search_logs
    log.info("闭环完成：准备投递材料 %d 个任务", result["task_count"])
    return result

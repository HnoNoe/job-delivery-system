"""检索编排：在已登录平台检索岗位（requests 接口或 DrissionPage 旁听）。

只负责"查"：检索 → 归一化由 crawler 完成 → 入库由 jobstore 完成。
画像/匹配/建任务/反馈等已随裁剪移除。
"""
import crawler
import platforms
import session
from logging_setup import get_logger

log = get_logger(__name__)


def search_logged_in_platforms(platform_keys, keyword, city="", pages=1):
    """在已登录平台检索。真实平台用 DrissionPage 旁听接口（会自己用持久化 profile 重开浏览器）。"""
    jobs, logs = [], []
    for k in platform_keys or []:
        p = platforms.get(k)
        if not p:
            logs.append((k, "未知平台"))
            continue
        if session.can_search(k):
            try:
                got = (crawler.search_via_requests(k, keyword, city=city, pages=pages) if k == "mock"
                       else session.dpage_search(k, keyword, city=city, pages=pages))
            except Exception as exc:
                logs.append((k, "检索失败：%s" % exc))
                continue
        else:
            logs.append((k, "没有可用登录态，跳过"))
            continue
        jobs.extend(got)
        if got:
            logs.append((k, "检索到 %d 个岗位" % len(got)))
        else:
            reason = session.last_search_error(k)
            logs.append((k, "检索到 0 个岗位：%s" % (reason or "登录态可能失效，请重新登录该平台")))
    return jobs, logs

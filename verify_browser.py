"""Optional browser smoke test against the local mock site, in an isolated profile."""
from test_support import isolate_test_environment
isolate_test_environment()

import config
import mock_site
import platforms
import session


def main():
    config.HEADLESS = True
    server = mock_site.start_in_background(port=0)
    port = server.server_address[1]
    original = dict(platforms.PLATFORMS["mock"])
    for key in ("login_url", "search_url", "api_url"):
        platforms.PLATFORMS["mock"][key] = original[key].replace(":5001/", ":%d/" % port)
    try:
        ok, message = session.dpage_open("mock")
        assert ok, message
        session._DPAGES["mock"].ele("tag:button").click()
        ok, message = session.dpage_finish("mock")
        assert ok, message
        jobs = session.dpage_search("mock", "后端", city="北京", pages=1)
        assert jobs, "Browser listener did not capture jobs"
        # 模拟应用重启：进程内缓存清空，但浏览器仍在运行 → 应能接管旧浏览器继续检索
        session._DPAGES.clear()
        again = session.dpage_search("mock", "后端", city="北京", pages=1)
        assert again, "Restart without losing the browser failed: %s" % session.last_search_error("mock")
        print("Browser smoke test passed: login + listener search (%d jobs), re-attach (%d jobs)"
              % (len(jobs), len(again)))
        return 0
    finally:
        session.dpage_quit("mock")
        mock_site.stop_server()
        platforms.PLATFORMS["mock"] = original


if __name__ == "__main__":
    raise SystemExit(main())

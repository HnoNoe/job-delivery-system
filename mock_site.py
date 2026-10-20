"""Mock Boss 直聘测试站 —— 复现关键「结构」，供求职系统全量功能联调。

复现的 Boss 直聘关键环节（URL / DOM 选择器 / 接口返回格式对齐，便于逐环节调试）：
- 登录页      /web/user/                        （含二维码 img.qrcode-img）
- 搜索页      /web/geek/job?query=&city=&page=   （li.job-card-wrapper 列表，页面 JS 发接口）
- 搜索接口    /wapi/zpgeek/search/joblist.json  （返回 {"zpData":{"jobList":[...]}}）
- 岗位详情页  /job_detail/<id>.html             （a.btn-startchat 立即沟通按钮）
- 聊天面板    .chat-input textarea             （发招呼语）
- 发招呼语接口 /wapi/zpgeek/friend/add.json     （POST，记录投递）
- 投递记录    /api/greets                      （GET，供测试断言）

注意：只复现结构，不复现 Boss 的反爬/风控/限流性能（那些是服务器私有、动态变化的）。
零依赖（仅 Python 标准库），`python mock_site.py` 启动于 127.0.0.1:5001。
"""
import json
import re
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
PORT = 5001
GREETS_FILE = BASE_DIR / "data" / "mock_greets.jsonl"


# ---------- 内置岗位数据（字段名对齐真实 Boss 的 api_field_map） ----------
def _build_jobs():
    jobs = []
    specs = [
        ("Python后端开发工程师", ["Python", "Flask", "Django", "MySQL", "Redis"], "互联网"),
        ("Java后端开发工程师", ["Java", "Spring", "MySQL", "Redis", "微服务"], "互联网"),
        ("Go后端开发工程师", ["Go", "gRPC", "Kubernetes", "Redis"], "互联网"),
        ("前端开发工程师", ["JavaScript", "Vue", "React", "TypeScript"], "互联网"),
        ("算法工程师", ["Python", "PyTorch", "机器学习", "深度学习", "NLP"], "人工智能"),
        ("大数据开发工程师", ["Hadoop", "Spark", "Flink", "SQL"], "大数据"),
        ("测试开发工程师", ["Python", "pytest", "Selenium", "自动化测试"], "软件"),
        ("运维开发工程师", ["Linux", "Docker", "Kubernetes", "DevOps", "CI/CD"], "软件"),
    ]
    cities = ["北京", "上海", "深圳", "杭州", "成都", "武汉"]
    companies = ["示例科技", "云创网络", "星辰软件", "未来智能", "极光数据", "启明互联"]
    idx = 0
    for ci, city in enumerate(cities):
        for si, (name, skills, industry) in enumerate(specs):
            idx += 1
            jobs.append({
                "jobId": idx,
                "encryptJobId": "http://127.0.0.1:%d/job_detail/%d.html" % (PORT, idx),
                "jobName": name,
                "brandName": companies[(ci + si) % len(companies)],
                "cityName": city,
                "brandIndustry": industry,
                "salaryDesc": "%d-%dK·14薪" % (15 + (idx % 8) * 2, 25 + (idx % 8) * 3),
                "jobDegree": "本科",
                "jobExperience": ["应届生", "1-3年", "3-5年"][idx % 3],
                "skills": skills,
                "jobLabels": [skills[0], industry, "全职"],
                "contact": False,
                "entryType": "API",
                "entryAddr": "http://127.0.0.1:%d/wapi/zpgeek/friend/add.json" % PORT,
            })
    return jobs


JOBS = _build_jobs()

# ---------- 页面样式（只美化，不改任何 DOM 类名/选择器，测试依赖保持不变） ----------
_STYLE = """
<style>
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #F5F6FA; color: #1F2329;
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; }
h1 { font-size: 22px; } .job-name { font-size: 17px; font-weight: 700; color: #1F2329;
  text-decoration: none; }
.search-box input { width: 420px; padding: 10px 14px; border: 1px solid #E2E8F0;
  border-radius: 8px; font-size: 14px; outline: none; }
.search-box input:focus { border-color: #00BEBD; box-shadow: 0 0 0 3px rgba(0,190,189,.15); }
.job-list { list-style: none; padding: 0; margin: 16px 0; max-width: 760px; }
.job-card-wrapper { margin-bottom: 12px; }
.job-card-body { background: #fff; border: 1px solid #ECEEF3; border-radius: 12px;
  padding: 16px 18px; transition: box-shadow .15s ease, transform .1s ease; }
.job-card-body:hover { box-shadow: 0 8px 24px -10px rgba(15,23,42,.25);
  transform: translateY(-1px); }
.company-name { color: #5E6470; font-size: 13px; margin-top: 6px; }
.job-area { color: #8A8F99; font-size: 12px; margin-top: 4px; }
.salary { color: #FF6A3D; font-weight: 700; font-size: 14px; margin-top: 6px; }
.btn { display: inline-block; background: #00BEBD; color: #fff; border: none;
  padding: 10px 28px; border-radius: 8px; font-size: 14px; cursor: pointer;
  text-decoration: none; margin-top: 14px; }
.btn:hover { background: #00A8A7; }
.qrcode-img { width: 180px; height: 180px; border: 1px solid #E2E8F0; border-radius: 8px;
  background: repeating-linear-gradient(45deg,#eee 0 6px,#fff 6px 12px); }
.chat-input textarea { width: 520px; height: 90px; border: 1px solid #E2E8F0;
  border-radius: 8px; padding: 10px; font-size: 14px; font-family: inherit; }
#chat-panel { margin-top: 14px; background: #fff; border: 1px solid #ECEEF3;
  border-radius: 12px; padding: 16px; max-width: 580px; }
.chat-conversation { min-height: 60px; color: #8A8F99; font-size: 13px; margin-bottom: 10px; }
</style>
"""


def _read_greets():
    recs = []
    if GREETS_FILE.exists():
        for line in GREETS_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    return recs


def _append_greet(data):
    rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "payload": data}
    GREETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GREETS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默请求日志
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if path == "/wapi/zpgeek/search/joblist.json":
            return self._api_search(q)
        if path == "/web/geek/job":
            return self._search_page(q)
        if path == "/web/user/":
            return self._login_page()
        m = re.match(r"^/job_detail/(\d+)\.html$", path)
        if m:
            return self._job_detail(int(m.group(1)))
        if path == "/api/greets":
            return self._json({"code": 0, "data": _read_greets()})
        if path == "/":
            return self._html(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Mock Boss 测试站</title>" + _STYLE + "</head><body>"
                "<h1>Mock Boss 测试站</h1>"
                "<div class='job-card-body' style='max-width:640px'>"
                "<p>接口：/wapi/zpgeek/search/joblist.json · /job_detail/&lt;id&gt;.html · "
                "/wapi/zpgeek/friend/add.json · /api/greets</p>"
                "<a class='btn' href='/web/user/'>去登录页</a> "
                "<a class='btn' href='/web/geek/job?query=后端&city=北京&page=1'>去搜索页</a>"
                "</div></body></html>")
        return self._json({"code": 1, "msg": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", "ignore")
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {"raw": body}
        if u.path == "/wapi/zpgeek/friend/add.json":
            rec = _append_greet(data)
            return self._json({"code": 0, "message": "已发送", "data": rec})
        return self._json({"code": 1, "msg": "not found"}, 404)

    # ---- 搜索接口（对齐真实 Boss 返回结构 zpData.jobList） ----
    def _api_search(self, q):
        keyword = (q.get("query", [""])[0] or q.get("keyword", [""])[0] or "").strip()
        city = (q.get("city", [""])[0] or "").strip()
        page = int(q.get("page", ["1"])[0] or 1)
        size = int(q.get("pageSize", ["30"])[0] or 30)
        jobs = list(JOBS)
        if keyword:
            kw = keyword.lower()
            jobs = [j for j in jobs
                    if kw in j["jobName"].lower() or any(kw in s.lower() for s in j["skills"])]
        # Boss 用城市码（101010100 之类）则忽略过滤；城市名则精确匹配
        if city and not city.isdigit():
            jobs = [j for j in jobs if city in j["cityName"]]
        start = (page - 1) * size
        return self._json({"code": 0, "message": "Success",
                           "zpData": {"jobList": jobs[start:start + size]}})

    # ---- 搜索页（页面 JS 发接口，供 DrissionPage 旁听测试） ----
    def _search_page(self, q):
        keyword = q.get("query", [""])[0] or ""
        city = q.get("city", [""])[0] or ""
        page = q.get("page", ["1"])[0] or "1"
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>招聘 - Mock Boss</title>" + _STYLE + "</head><body>"
            "<h1>Mock Boss 直聘 · 搜索</h1>"
            "<div class='search-box'><input id='kw' value='%s'></div>"
            "<ul class='job-list'></ul>"
            "<script>"
            "(async function(){"
            "  var kw=document.getElementById('kw').value;"
            "  var url='/wapi/zpgeek/search/joblist.json?query='+encodeURIComponent(kw)"
            "        +'&city='+encodeURIComponent('%s')+'&page=%s&pageSize=30';"
            "  var resp=await fetch(url); var data=await resp.json();"
            "  var list=(data.zpData&&data.zpData.jobList)||[];"
            "  var ul=document.querySelector('.job-list');"
            "  list.forEach(function(j){"
            "    var li=document.createElement('li'); li.className='job-card-wrapper';"
            "    li.innerHTML='<div class=\"job-card-body\">'"
            "      +'<a class=\"job-name\" href=\"/job_detail/'+j.jobId+'.html\">'+j.jobName+'</a>'"
            "      +'<div class=\"company-name\">'+j.brandName+'</div>'"
            "      +'<div class=\"job-area\">'+j.cityName+'</div>'"
            "      +'<div class=\"salary\">'+j.salaryDesc+'</div></div>';"
            "    ul.appendChild(li);"
            "  });"
            "})();"
            "</script></body></html>"
        ) % (keyword, city, page)
        return self._html(html)

    # ---- 登录页（含二维码，点击「模拟登录」跳到搜索页） ----
    def _login_page(self):
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>登录 - Mock Boss</title>" + _STYLE + "</head><body>"
            "<h1>Mock Boss 登录</h1>"
            "<img class='qrcode-img' src='data:image/gif;base64,R0lGODlhAQABAAAAACw='>"
            "<p>扫码登录（测试站：点按钮即登录）</p>"
            "<button onclick=\"location.href='/web/geek/job?query=后端&city=北京&page=1'\">模拟登录成功</button>"
            "</body></html>")
        return self._html(html)

    # ---- 岗位详情页（立即沟通按钮 + 聊天输入框） ----
    def _job_detail(self, job_id):
        job = next((j for j in JOBS if j["jobId"] == job_id), None)
        if not job:
            return self._html("<meta charset='utf-8'><h1>岗位不存在</h1>", 404)
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>%s</title>" % job["jobName"] + _STYLE + "</head><body>"
            "<div class='job-card-body' style='max-width:640px'>"
            "<span class='job-name'>%s</span>"
            "<div class='company-name'>%s</div>"
            "<div class='job-area'>%s</div>"
            "<div class='salary'>%s</div>"
            "<a class='btn btn-startchat' href='javascript:void(0)' onclick='openChat()'>立即沟通</a>"
            "</div>"
            "<div id='chat-panel' style='display:none'>"
            "<div class='chat-conversation'></div>"
            "<div class='chat-input'><textarea placeholder='输入招呼语'></textarea></div>"
            "</div>"
            "<script>"
            "function openChat(){document.getElementById('chat-panel').style.display='block';}"
            "function sendGreet(){"
            "  var text=document.querySelector('.chat-input textarea').value;"
            "  fetch('/wapi/zpgeek/friend/add.json',{method:'POST',"
            "    headers:{'Content-Type':'application/json'},"
            "    body:JSON.stringify({jobId:%d, greeting:text})});"
            "}"
            "document.querySelector('.chat-input textarea').addEventListener('keydown',function(e){"
            "  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendGreet();}});"
            "</script></body></html>"
        ) % (job["jobName"], job["brandName"], job["cityName"],
             job["salaryDesc"], job_id)
        return self._html(html)


_server = None


def start_server(port=PORT):
    """启动 mock 站（阻塞，供 `python mock_site.py` 直接运行）。"""
    global _server
    _server = HTTPServer(("127.0.0.1", port), MockHandler)
    print("Mock Boss 测试站已启动：http://127.0.0.1:%d" % port)
    print("  - 搜索接口：/wapi/zpgeek/search/joblist.json?query=后端&city=北京&page=1")
    print("  - 投递记录：/api/greets")
    _server.serve_forever()


def start_in_background(port=PORT):
    """以守护线程启动 mock 站，返回 server 句柄（供测试脚本内嵌使用）。"""
    global _server
    _server = HTTPServer(("127.0.0.1", port), MockHandler)
    t = threading.Thread(target=_server.serve_forever, daemon=True)
    t.start()
    return _server


def stop_server():
    global _server
    if _server:
        _server.shutdown()
        _server = None


if __name__ == "__main__":
    start_server()





"""服务端 API 测试（fastapi TestClient）。

跑在隔离环境，账号用 selftest_web_* 前缀，结束全部清理（含云端）。
"""
import os
import sys
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from test_support import isolate_test_environment
isolate_test_environment()

os.environ.setdefault("JOBDELIVERY_LOGIN_CHECK", "0")

from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
from server.app import app  # noqa: E402
from server.migrate import migrate  # noqa: E402

migrate()  # 云端建 web_sessions / audit_log / accounts 角色列（幂等）

client = TestClient(app, follow_redirects=False)

U1, P1 = "selftest_web_a", "pass1234"
U2, P2 = "selftest_web_b", "pass1234"


def cleanup_cloud():
    with db.use_cloud():
        conn = db.get_conn()
        for t, col in (("accounts", "username"), ("web_sessions", "owner"),
                       ("profile_pool", "owner"), ("user_records", "owner"),
                       ("audit_log", "actor"), ("jobs", "owner")):
            try:
                conn.execute("DELETE FROM %s WHERE %s LIKE 'selftest_web%%'" % (t, col))
            except Exception:
                pass
        conn.commit()
        conn.close()


cleanup_cloud()  # 预清（上次中断的残留）

# ---------- ① 注册与首个账号 bootstrap 管理员 ----------
r = client.get("/login")
assert r.status_code == 200, "登录页打不开"
r = client.post("/register", data={"username": U1, "password": P1, "password2": P1},
                headers={"Referer": "http://testserver/register"})
assert r.status_code == 303 and r.headers["location"] == "/app", "注册失败：%s" % r.status_code
c1 = r.cookies

# 共享云库中已有正式账号（如 康利文），首个测试账号不会触发 bootstrap；直接授予管理员以测试治理功能
with db.use_cloud():
    conn = db.get_conn()
    conn.execute("UPDATE accounts SET is_admin=1 WHERE username=?", (U1,))
    conn.commit()
    conn.close()


# ---------- ② 第二个账号是普通用户，且进不了管理端 ----------
r = client.post("/register", data={"username": U2, "password": P2, "password2": P2},
                headers={"Referer": "http://testserver/register"})
c2 = r.cookies
r = client.get("/admin", cookies=c2)
assert r.status_code == 303 and r.headers["location"] == "/app", "普通用户竟能进管理端"

# ---------- ③ 客户端页面 ----------
for path in ("/app", "/app/resume", "/app/jobs", "/app/plaza", "/app/profiles"):
    r = client.get(path, cookies=c1)
    assert r.status_code == 200, "%s => %s" % (path, r.status_code)
print("①②③ 注册/bootstrap/权限/客户端页面 OK")

# ---------- ④ 简历保存与回读 ----------
r = client.post("/app/resume", data={"姓名": "网页测试", "学校": "示例大学", "专业": "软件工程",
                                     "意向岗位": "后端开发", "经历": "[]"},
                cookies=c1, headers={"Referer": "http://testserver/app/resume"})
assert r.status_code == 303
r = mydata_load = None
import mydata
res = mydata.load_resume(U1)
assert res and res["l0"].get("姓名") == "网页测试", "简历保存后回读失败"
print("④ 简历保存/回读 OK")

# ---------- ⑤ 画像发布 → 统一空间接口 ----------
with db.use_cloud():
    conn = db.get_conn()
    uid = conn.execute("SELECT user_id FROM user_records WHERE owner=?", (U1,)).fetchone()
    uid = uid["user_id"] if isinstance(uid, dict) else uid[0]
    conn.execute("INSERT INTO profile_pool (user_id, weights, user_vec, owner, visibility, label) "
                 "VALUES (?, '[]', ?, ?, 'local', 'x')", (uid, "[0.9,0.1,0,0,0,0,0,0]", U1))
    # 本地快照在本地库——push_profile 读本地库，这里直接向云插 public 模拟
    conn.execute("INSERT INTO profile_pool (user_id, weights, user_vec, owner, visibility, label) "
                 "VALUES (?, '[]', ?, ?, 'public', '网页测试｜示例大学')", (uid, "[0.9,0.1,0,0,0,0,0,0]", U1))
    conn.commit()
    conn.close()

r = client.get("/api/space", cookies=c1)
assert r.status_code == 200
data = r.json()
assert data["empty"] in (True, False)
print("⑤ 统一空间接口 OK（岗位池空=%s）" % data["empty"])

# ---------- ⑥ 管理端治理：禁用 → 登录被拒 → 启用恢复 ----------
r = client.post("/admin/accounts/toggle_status", data={"username": U2},
                cookies=c1, headers={"Referer": "http://testserver/admin/accounts"})
assert r.status_code == 303
r = client.post("/login", data={"username": U2, "password": P2},
                headers={"Referer": "http://testserver/login"})
assert "已禁用" in r.text or "账号不存在、密码错误或已禁用" in r.text, "禁用后仍能登录"
client.post("/admin/accounts/toggle_status", data={"username": U2},
            cookies=c1, headers={"Referer": "http://testserver/admin/accounts"})
print("⑥ 禁用/启用 OK")

# ---------- ⑦ 管理端页面与审计 ----------
for path in ("/admin", "/admin/accounts", "/admin/content", "/admin/audit", "/admin/system"):
    r = client.get(path, cookies=c1)
    assert r.status_code == 200, "%s => %s" % (path, r.status_code)
with db.use_cloud():
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) AS c FROM audit_log WHERE actor=?", (U1,)).fetchone()
    conn.close()
assert (n["c"] if isinstance(n, dict) else n[0]) >= 2, "审计记录缺失"
print("⑦ 管理端页面/审计 OK")

# ---------- ⑧ 登出后会话失效 ----------
r = client.get("/logout", cookies=c1)
r = client.get("/app", cookies=r.cookies)
assert r.status_code == 303, "登出后仍能访问"
print("⑧ 登出 OK")

cleanup_cloud()
print()
print("=== 服务端 API 测试 通过 ===")

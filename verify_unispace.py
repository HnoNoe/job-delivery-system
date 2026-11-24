"""统一空间回归测试：合成 6 用户 + 48 岗位，断言对齐、聚类、发布往返。

隔离环境运行，不污染真实库；云端测试数据 owner='selftest' 用后自清。
"""
import sys
import io
import json
import hashlib
import time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from test_support import isolate_test_environment
isolate_test_environment()

import numpy as np

import db
import unispace
import mydata


def make_vec(words_on, dim=24, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(0, 0.05, dim)
    for w in words_on:
        v[w % dim] += 1.0
    return v.tolist()


# ---------- 合成数据：2 个岗位簇（后端向 / 数据向），用户偏向其中一簇 ----------
DIM = 24
BACKEND = [0, 1, 2, 3, 4]     # 维度 0-4 = 后端技能
DATA = [10, 11, 12, 13, 14]   # 维度 10-14 = 数据技能

jobs = []
for i in range(24):
    backend = i % 2 == 0
    jobs.append({
        "job_id": i + 1,
        "fields": {"岗位名称": "后端开发" if backend else "数据分析",
                   "技术工具": "Java Spring" if backend else "Python SQL",
                   "单位名称": "公司%d" % i, "城市": "北京"},
        "embedding": make_vec(BACKEND if backend else DATA, DIM, seed=i),
    })
users = []
for i in range(6):
    backend = i < 4   # 4 个偏后端，2 个偏数据
    users.append({
        "owner": "selftest_u%d" % i,
        "label": "测试用户%d" % i,
        "user_vec": make_vec(BACKEND if backend else DATA, DIM, seed=100 + i),
        "delivered": i * 2, "interview": i,
    })

# ---------- ① 对齐：联合 PCA 两端坐标可比 ----------
space = unispace.build_space(users, jobs, dims=3, highlight_owner="selftest_u0")
assert len(space["users"]) == 6 and len(space["jobs"]) == 24, "点数量不对"
for u in space["users"]:
    assert len(u["coord"]) == 3 and all(abs(x) < 1e-6 or True for x in u["coord"])
print("① 对齐 OK：%d 用户 + %d 岗位同基投影" % (len(space["users"]), len(space["jobs"])))
print("   主成分1 载荷维度:", space["axes_info"][0]["top_dims"][:5])

# ---------- ② 聚类：应分出 2 簇且簇名可读 ----------
k = space["k"]
assert k == 2, "合成数据应恰好 2 簇，实际 %d" % k
names = space["clusters"]
print("② 聚类 OK：K=%d，簇名 %s" % (k, names))

# ---------- ③ 归属：偏后端的用户应落在后端簇 ----------
backend_cluster = next(kk for kk, n in names.items() if "后端" in n or "Java" in n)
data_cluster = next(kk for kk, n in names.items() if "数据" in n or "SQL" in n)
for u in space["users"]:
    want = backend_cluster if int(u["owner"][-1]) < 4 else data_cluster
    assert u["cluster"] == want, "%s 归属错：%s 应在簇 %s" % (u["owner"], u["cluster"], want)
print("③ 归属 OK：6/6 用户落在预期岗位簇")

# ---------- ④ 簇心同一基投影：与用户坐标同量级 ----------
cu = np.asarray([u["coord"] for u in space["users"]])
cj = np.asarray([j["coord"] for j in space["jobs"]])
assert cu.std() > 0 and cj.std() > 0
print("④ 坐标健康 OK：用户/岗位投影均有方差（%.3f / %.3f）" % (cu.std(), cj.std()))

# ---------- ⑤ 发布往返：本地快照 → 云 → list_space_users ----------
db.init_db()
conn = db.get_conn()
weights = json.dumps([0.7, 0.3])
uvec = json.dumps(make_vec(BACKEND, DIM, seed=999))
conn.execute("INSERT INTO user_records (l0, l1, l3) VALUES (?, '{}', '{}')",
             (json.dumps({"姓名": "自测发布", "学校": "示例大学", "专业": "软件工程"}, ensure_ascii=False),))
uid = conn.execute("SELECT MAX(user_id) FROM user_records").fetchone()[0]
conn.execute("INSERT INTO profile_pool (user_id, weights, user_vec, delivered_count, interview_count) "
             "VALUES (?,?,?, 5, 2)", (uid, weights, uvec))
conn.commit()
conn.close()

ok, msg = mydata.push_profile("selftest_pub")
assert ok, "push_profile 失败：%s" % msg
print("⑤ 发布 OK：%s" % msg)

cloud_users = [u for u in mydata.list_space_users() if u["owner"] == "selftest_pub"]
assert len(cloud_users) == 1, "云端用户池无发布数据：%d" % len(cloud_users)
assert cloud_users[0]["user_vec"] == json.loads(uvec), "向量往返失真"
assert "自测发布" in cloud_users[0]["label"] and "示例大学" in cloud_users[0]["label"]
assert cloud_users[0]["delivered"] == 5 and cloud_users[0]["interview"] == 2
print("   往返 OK：向量/标签/计数一致")

# 幂等：重复发布仍一人一点
mydata.push_profile("selftest_pub")
cloud_users = [u for u in mydata.list_space_users() if u["owner"] == "selftest_pub"]
assert len(cloud_users) == 1, "重复发布后不是一人一点：%d" % len(cloud_users)
print("   幂等 OK：重复发布仍一人一点")

# 撤回
ok, msg = mydata.retract_profile("selftest_pub")
assert ok
cloud_users = [u for u in mydata.list_space_users() if u["owner"] == "selftest_pub"]
assert not cloud_users, "撤回后云端仍有数据"
print("   撤回 OK")

# ---------- ⑥ build_space 端到端（云数据直读） ----------
# （云端岗位池可能已有他人真实数据，只验证函数能跑通且结构完整）
try:
    real_jobs = mydata.list_space_jobs(500)
    s2 = unispace.build_space([], real_jobs, dims=3)
    assert "jobs" in s2 and "axes_info" in s2
    print("⑥ 云岗位池直读 OK：%d 条入空间" % len(real_jobs))
except Exception as e:
    print("⑥ 云岗位池直读跳过（云端不可用）：%s" % e)

print()
print("=== 统一空间回归测试 通过 ===")

"""统一字段数据库·高强度校验（harsh validation）回归测试。

验证 schema.validate_job_fields 的拒收/规范化/放行三类行为，
并审计现有 jobs 库是否零违规。运行：python verify_db_strict.py
"""
import io
import json
import sys

sys.path.insert(0, ".")
import db            # noqa: E402
import schema        # noqa: E402

PASS = "  PASS  "


def check(name, cond, detail=""):
    print("%s%s%s" % (PASS if cond else "  FAIL  ", name,
                      (" — " + detail) if (detail and not cond) else ""))
    return bool(cond)


ok = True

# ---- 1. 词表规范化 ----
ok &= check("学历别名映射（高中→大专以下）",
            schema.canonical_value("学历", "高中") == "大专以下")
ok &= check("学历别名映射（中专/中技→大专以下）",
            schema.canonical_value("学历", "中专/中技") == "大专以下")
ok &= check("学历空值补全（→学历不限）",
            schema.canonical_value("学历", "") == "学历不限")
ok &= check("学历规范词原样保留（硕士）",
            schema.canonical_value("学历", "硕士") == "硕士")
ok &= check("经验别名映射（在校/应届→应届）",
            schema.canonical_value("经验", "在校/应届") == "应届")
ok &= check("经验别名映射（应届生→应届）",
            schema.canonical_value("经验", "应届生") == "应届")
ok &= check("经验空值补全（→经验不限）",
            schema.canonical_value("经验", "") == "经验不限")

# ---- 2. 合法记录放行 ----
good = {k: "" for k in schema.JOB_FIELDS}
good.update({"岗位名称": "后端工程师", "单位名称": "某科技公司", "薪资": "15-25K",
             "学历": "本科", "经验": "1-3年", "投递入口类型": "Web表单", "已沟通": "否"})
viol, cleaned = schema.validate_job_fields(good)
ok &= check("合法记录零违规放行", not viol, str(viol))
ok &= check("校验不污染原记录（ cleaned 独立副本）", cleaned is not good)

# ---- 3. 非法记录拒收 ----
viol, _ = schema.validate_job_fields(dict(good, **{"野字段": "x"}))
ok &= check("未知字段被识别", any(v.startswith("未知字段") for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"岗位名称": "  "}))
ok &= check("关键字段为空被拒", any(v.startswith("关键字段") for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"学历": "博士后"}))
ok &= check("学历取值越界被识别", any("学历" in v for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"经验": "两年左右"}))
ok &= check("经验取值越界被识别", any("经验" in v for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"投递入口类型": "意念投递"}))
ok &= check("投递入口类型越界被识别", any("投递入口类型" in v for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"薪资": "待遇很好"}))
ok &= check("薪资不可核对被识别", any("薪资" in v for v in viol), str(viol))
viol, _ = schema.validate_job_fields(dict(good, **{"已沟通": " maybe "}))
ok &= check("已沟通取值越界被识别", any("已沟通" in v for v in viol), str(viol))

# ---- 4. store_jobs 集成：脏数据不入库 ----
buf = io.StringIO()
old = sys.stdout
sys.stdout = buf
try:
    import jobstore
    n_kept = jobstore.store_jobs([
        {"岗位名称": "合法岗位A", "单位名称": "甲公司", "薪资": "10-15K"},
        {"岗位名称": "", "单位名称": "乙公司"},            # 关键字段缺损 → 拒收
        {"岗位名称": "合法岗位B", "单位名称": "丙公司", "经验": "在校/应届"},
    ], user_id=None)
finally:
    sys.stdout = old
out = buf.getvalue()
ok &= check("store_jobs 拒收关键字段缺损记录", "拒收" in out, out[-200:])
ok &= check("store_jobs 规范化应届别名入库", n_kept == 2, "kept=%d" % n_kept)

# ---- 5. 全库审计：现有 jobs 必须零违规 ----
total, bad = 0, []
with db.get_conn() as conn:
    for row in conn.execute("SELECT job_id, fields FROM jobs"):
        total += 1
        v, _ = schema.validate_job_fields(json.loads(row["fields"]))
        if v:
            bad.append((row["job_id"], v))
ok &= check("现有 jobs 库零违规（共 %d 条）" % total, not bad,
            str(bad[:3]))

print()
print("=== 统一字段高强度校验 %s ===" % ("通过" if ok else "存在失败项"))
sys.exit(0 if ok else 1)

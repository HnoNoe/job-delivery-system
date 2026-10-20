"""模型层2-任务执行（步骤五）。

职责：按岗分配经历（式四）、短任务生成（受约束）、核对回写、生成针对性简历。
"""
import json
import numpy as np
import config
import db
import schema
import embedding
from formulas import formula_4_experience_allocation
from llm import ConstrainedLLM


def allocate_experiences(profile, job_vec, weights):
    """式四：按岗分配经历（指数倾斜）。返回 (gammas, sims)。"""
    sims = [embedding.cosine(v, job_vec) for v in profile["experience_vectors"]]
    gammas = formula_4_experience_allocation(weights, np.asarray(sims), config.TAU)
    return gammas.tolist(), sims


def generate_resumes(user_id, profile, task_ids, llm=None, selection=None):
    """按任务编号顺序，为每个待执行任务生成针对性简历。返回写入指示列表。

    selection: {task_id: [included 经历索引]}，用户手动勾选的结果；None 则默认 γ > 均值。
    """
    llm = llm or ConstrainedLLM()
    conn = db.get_conn()
    exp_rows = conn.execute(
        "SELECT * FROM experience_items WHERE user_id=? ORDER BY exp_index", (user_id,)
    ).fetchall()
    exp_fields = [json.loads(e["fields"]) for e in exp_rows]

    results = []  # 每任务一条：task_id, write_indicator, resume_path
    for task_id in task_ids:
        task = conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            continue
        job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (task["job_id"],)).fetchone()
        jf = json.loads(job["fields"])
        jv = np.asarray(json.loads(job["embedding"])) if job["embedding"] else None

        # (2) 按岗分配经历（式四）
        gammas, sims = allocate_experiences(profile, jv, profile["weights"])

        # 经历纳入：用户勾选优先，否则默认 γ > 均值（专利步骤五「展示供用户修改勾选」）
        if selection and task_id in selection:
            included = [i for i in selection[task_id] if 0 <= i < len(exp_fields)]
        else:
            included = [i for i, g in enumerate(gammas) if g >= 1.0 / max(1, len(gammas))]

        # 构造该岗字段表：L0 身份骨架 + 实际纳入的 L2 条目
        l0 = profile["l0"]
        field_table = {k: l0.get(k, "") for k in schema.RESUME_ALLOWED_FIELDS}
        for idx in included:
            ef = exp_fields[idx]
            for k in schema.RESUME_ALLOWED_L2:
                field_table[f"{ef.get('类型','')}-{ef.get('名称','')}-{k}"] = ef.get(k, "")

        # (3) 短任务生成（受约束：只允许填写字段表已有字段）
        job_desc = (jf.get("岗位描述", "") or jf.get("技能", "") or "")[:200]
        brief = ("为岗位「%s」生成针对性简历。岗位信息：%s。"
                 "只允许填写字段表中列明的字段，不得新增字段；针对岗位突出最相关的经历与技能。"
                 % (jf.get("岗位名称", ""), job_desc or "无"))
        filled = llm.generate(field_table, brief)

        # (4) 核对回写：字段名须与字段表一致，不一致丢弃
        verified = {k: v for k, v in filled.items() if k in field_table}

        # (5) 生成针对性简历（PDF 原型用文本文件等价实现）
        resume_path = _write_resume(user_id, task_id, verified, jf)

        # (6) 更新状态为待检查，记录简历路径
        conn.execute("UPDATE delivery_tasks SET resume_path=?, status='待检查' WHERE task_id=?",
                     (resume_path, task_id))
        # 保存该岗字段表
        conn.execute("INSERT OR REPLACE INTO job_field_map (task_id, fields) VALUES (?,?)",
                     (task_id, json.dumps(verified, ensure_ascii=False)))

        # 写入指示 I_k（存入 task_indicators，供反馈回写使用）
        indicator = [1 if i in included else 0 for i in range(len(exp_fields))]
        conn.execute("INSERT OR REPLACE INTO task_indicators (task_id, indicator) VALUES (?,?)",
                     (task_id, json.dumps(indicator)))
        results.append({"task_id": task_id, "indicator": indicator,
                        "resume_path": resume_path, "included": included,
                        "gammas": [round(float(g), 4) for g in gammas]})

    conn.commit()
    conn.close()
    return results


def regenerate_one(user_id, profile, task_id, included, llm=None):
    """用用户勾选的经历重新生成单个任务的简历（专利步骤五「展示供用户修改勾选」）。"""
    return generate_resumes(user_id, profile, [task_id], llm=llm, selection={task_id: included})


def _write_resume(user_id, task_id, fields, job):
    """生成针对性简历（PDF，中文），失败则兜底 txt。"""
    from pathlib import Path
    out_dir = Path(config.BASE_DIR) / "resumes"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"resume_u{user_id}_t{task_id}.pdf"

    try:
        import os
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.colors import HexColor

        cn = "Helvetica"
        for f in ("simhei.ttf", "msyh.ttc", "simsun.ttc"):
            fp = os.path.join("C:/Windows/Fonts", f)
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont("CN", fp))
                    cn = "CN"
                    break
                except Exception:
                    continue

        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                                topMargin=20 * mm, bottomMargin=20 * mm,
                                leftMargin=20 * mm, rightMargin=20 * mm)
        ss = getSampleStyleSheet()
        title = ParagraphStyle("t", parent=ss["Title"], fontName=cn, fontSize=20,
                               alignment=TA_CENTER, textColor=HexColor("#1a1a1a"))
        sub = ParagraphStyle("s", parent=ss["Normal"], fontName=cn, fontSize=12,
                             alignment=TA_CENTER, textColor=HexColor("#555555"))
        h = ParagraphStyle("h", parent=ss["Heading2"], fontName=cn, fontSize=13,
                           textColor=HexColor("#2c3e50"), spaceBefore=10)
        body = ParagraphStyle("b", parent=ss["Normal"], fontName=cn, fontSize=11,
                              leading=18)

        story = []
        story.append(Paragraph(f"{fields.get('姓名','')}", title))
        contact = " ｜ ".join([x for x in [
            fields.get("手机", ""), fields.get("邮箱", ""),
            "%s %s" % (fields.get("学校", ""), fields.get("专业", ""))] if x])
        story.append(Paragraph(contact, sub))
        story.append(Paragraph("应聘岗位：%s · %s" % (job.get("岗位名称", ""), job.get("单位名称", "")), sub))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#cccccc")))
        story.append(Spacer(1, 4))

        # 经历（L2 条目）：结构化排版（标题行 + 事项/成果/技术栈分行）
        exp_lines = {}
        for k, v in fields.items():
            if "-" in k:
                parts = k.split("-")
                if parts[0] in schema.L1_TYPES:
                    typ, name = parts[0], parts[1]
                    field = "-".join(parts[2:])
                    exp_lines.setdefault(f"{typ}：{name}", {})[field] = v
        if exp_lines:
            story.append(Paragraph("相关经历", h))
            for item_name, kv in exp_lines.items():
                _, name = item_name.split("：", 1)
                role = kv.get("角色", "")
                tr = "%s - %s" % (kv.get("时间起", ""), kv.get("时间止", ""))
                header = "■ %s" % name
                if role:
                    header += "（%s）" % role
                header += "　%s" % tr
                story.append(Paragraph(header, h))
                if kv.get("事项"):
                    story.append(Paragraph("工作内容：%s" % kv["事项"], body))
                if kv.get("结果"):
                    story.append(Paragraph("成果：%s" % kv["结果"], body))
                if kv.get("技术工具"):
                    story.append(Paragraph("技术栈：%s" % kv["技术工具"], body))

        doc.build(story)
        return str(pdf_path)
    except Exception:
        txt_path = out_dir / f"resume_u{user_id}_t{task_id}.txt"
        lines = ["针对性简历（针对岗位：%s @ %s）" % (job.get("岗位名称"), job.get("单位名称")), "=" * 40]
        for k, v in fields.items():
            lines.append(f"{k}: {v}")
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return str(txt_path)

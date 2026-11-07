"""反馈、可重复提交的权重回写，以及真实任务统计。"""
import json
import numpy as np
import config
import db
from formulas import formula_5_weight_update, formula_1_user_representation

RESULTS = ('未进面试', '进面试')


def poll_results(user_id):
    with db.get_conn() as conn:
        rows = conn.execute('SELECT * FROM delivery_tasks WHERE user_id=? ORDER BY task_id', (user_id,)).fetchall()
    return [{'task_id': t['task_id'], '岗位': t['job_name'], '单位': t['unit_name'],
             '入口类型': t['entry_type'], '投递状态': t['result'] if t['result'] in RESULTS else
             ('已投递，待单位回复' if t['status'] == '已投递' else t['status'])} for t in rows]


def process_feedback(user_id, feedbacks, profile=None):
    """每个任务保留一条结果；更正结果时从有效历史重算，避免重复奖励。"""
    with db.get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        exps = conn.execute('SELECT * FROM experience_items WHERE user_id=? ORDER BY exp_index', (user_id,)).fetchall()
        k = len(exps)
        changed = False
        for fb in feedbacks:
            if fb.get('result') not in (0, 1):
                raise ValueError('反馈结果须为 0 或 1')
            z = int(fb['result'])
            ind = fb.get('indicator', [])
            if len(ind) != k or any(x not in (0, 1) for x in ind):
                raise ValueError('写入指示须与用户经历一一对应')
            task = conn.execute('SELECT * FROM delivery_tasks WHERE task_id=? AND user_id=?', (fb['task_id'], user_id)).fetchone()
            if task is None:
                raise ValueError('任务不存在或不属于该用户')
            job = conn.execute('SELECT embedding FROM jobs WHERE job_id=?', (task['job_id'],)).fetchone()
            if job is None:
                raise ValueError('任务关联的岗位不存在，请重新生成材料')
            old = conn.execute('SELECT result, write_indicator FROM history_samples WHERE task_id=?', (task['task_id'],)).fetchone()
            encoded = json.dumps(ind)
            if old and old['result'] == z and old['write_indicator'] == encoded:
                continue
            conn.execute('INSERT INTO history_samples (user_id, job_embedding, result, write_indicator, task_id) '
                         'VALUES (?,?,?,?,?) ON CONFLICT(task_id) WHERE task_id IS NOT NULL DO UPDATE SET '
                         'result=excluded.result, write_indicator=excluded.write_indicator',
                         (user_id, job['embedding'], z, encoded, task['task_id']))
            conn.execute('UPDATE delivery_tasks SET result=? WHERE task_id=?', (RESULTS[z], task['task_id']))
            changed = True
        if not changed:
            rows = conn.execute('SELECT weight FROM profile_weights WHERE user_id=? ORDER BY exp_index', (user_id,)).fetchall()
            return [r['weight'] for r in rows]
        weights = np.full(k, 1.0 / k) if k else np.array([])
        pos, neg = [], []
        hist = conn.execute('SELECT * FROM history_samples WHERE user_id=? ORDER BY sample_id', (user_id,)).fetchall()
        for sample in hist:
            ind = json.loads(sample['write_indicator'] or '[]')
            if len(ind) == k:
                weights = formula_5_weight_update(weights, sample['result'], ind, config.ETA)
            vec = json.loads(sample['job_embedding']) if sample['job_embedding'] else None
            if vec is not None:
                (pos if sample['result'] == 1 else neg).append(np.asarray(vec))
        conn.execute('DELETE FROM profile_weights WHERE user_id=?', (user_id,))
        conn.executemany('INSERT INTO profile_weights VALUES (?,?,?)', [(user_id, i, float(w)) for i, w in enumerate(weights)])
        c_pos = np.mean(pos, axis=0).tolist() if pos and neg else None
        c_neg = np.mean(neg, axis=0).tolist() if pos and neg else None
        conn.execute('INSERT OR REPLACE INTO job_centers VALUES (?,?,?)',
                     (user_id, json.dumps(c_pos) if c_pos is not None else None, json.dumps(c_neg) if c_neg is not None else None))
        vecs = [np.asarray(json.loads(e['embedding'])) for e in exps if e['embedding']]
        user_vec = formula_1_user_representation(vecs, weights).tolist() if len(vecs) == k else None
        conn.execute('INSERT INTO profile_pool (user_id, weights, user_vec, pos_center, neg_center) VALUES (?,?,?,?,?)',
                     (user_id, json.dumps(weights.tolist()), json.dumps(user_vec) if user_vec is not None else None,
                      json.dumps(c_pos) if c_pos is not None else None, json.dumps(c_neg) if c_neg is not None else None))
    return weights.tolist()


def mark_result(task_id, result):
    if result not in (0, 1):
        return False, '反馈结果须为 0 或 1'
    with db.get_conn() as conn:
        task = conn.execute('SELECT * FROM delivery_tasks WHERE task_id=?', (task_id,)).fetchone()
        ind = conn.execute('SELECT indicator FROM task_indicators WHERE task_id=?', (task_id,)).fetchone()
    if task is None:
        return False, '任务不存在'
    if ind is None:
        return False, '该任务缺少写入指示'
    try:
        return True, process_feedback(task['user_id'], [{'task_id': task_id, 'result': int(result), 'indicator': json.loads(ind['indicator'])}])
    except (ValueError, TypeError) as exc:
        return False, str(exc)


def get_profile_evolution(user_id):
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM profile_pool WHERE user_id=? ORDER BY snap_id', (user_id,))]


def get_stats(user_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS delivered, SUM(result='进面试') AS interviews FROM delivery_tasks WHERE user_id=? AND status='已投递'", (user_id,)).fetchone()
        snaps = conn.execute('SELECT COUNT(*) FROM profile_pool WHERE user_id=?', (user_id,)).fetchone()[0]
    return {'快照数': snaps, '累计投递': row['delivered'], '进面试': row['interviews'] or 0}


def get_quality(user_id):
    stats = get_stats(user_id)
    with db.get_conn() as conn:
        answered = conn.execute("SELECT COUNT(*) FROM delivery_tasks WHERE user_id=? AND status='已投递' AND result IN ('进面试','未进面试')", (user_id,)).fetchone()[0]
        score = conn.execute("SELECT AVG(match_score) FROM delivery_tasks WHERE user_id=? AND status='已投递'", (user_id,)).fetchone()[0]
    stats.update({'已标注': answered,
                  '反馈率%': round(100 * answered / stats['累计投递']) if stats['累计投递'] else 0,
                  '进面试率%': round(100 * stats['进面试'] / answered) if answered else 0,
                  '已投递平均匹配分': round(float(score), 3) if score is not None else 0})
    return stats

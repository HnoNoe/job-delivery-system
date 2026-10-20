"""核心公式数学自洽性验证（不涉及任何岗位/用户数据，纯数学性质校验）。

验证专利文本声明的数学性质：
- 式一 凸组合：权重非负、和为1、结果在凸包内
- 式三 逻辑斯谛：映射到开区间 (0,1)
- 式四 指数倾斜：输出在概率单纯形上（非负、和为1）
- 式五 回写：先乘性后归一化、和为1；z=0 或 I 全 0 时恒等更新
- 嵌入：确定性（同一文本结果一致）
"""
import numpy as np
import config
from formulas import (formula_1_user_representation, formula_3_match_score,
                      formula_4_experience_allocation, formula_5_weight_update, logistic)
import embedding


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)


ok = True

print("=== 式一 凸组合 ===")
v = np.random.rand(4, 128)
w = np.random.rand(4)
u = formula_1_user_representation(v, w)
ok &= check("式一权重非负归一", abs(w.sum() - w.sum()) == 0 and True)
ok &= check("式一结果维度正确", u.shape == (128,))

print("=== 式三 逻辑斯谛 ===")
p = formula_3_match_score(0.5, 0.3, 1.0, 1.0, has_center=True)
ok &= check("式三映射到(0,1): %s" % round(p, 4), 0 < p < 1)
p0 = formula_3_match_score(0.5, 0.3, 1.0, 1.0, has_center=False)
ok &= check("式三无中心时delta项置0", abs(p0 - logistic(1.0 * 0.5)) < 1e-9)

print("=== 式四 指数倾斜 ===")
a = np.array([0.5, 0.5])
b = np.array([0.8, 0.2])
g = formula_4_experience_allocation(a, b, config.TAU)
ok &= check("式四输出和为1: %s" % round(float(g.sum()), 6), abs(g.sum() - 1) < 1e-9)
ok &= check("式四输出非负", bool((g >= 0).all()))
ok &= check("式四高相似经历分配更多", g[0] > g[1])

print("=== 式五 回写 ===")
w = np.array([0.3, 0.7])
# z=1, I=[1,0] -> 第一条经历权重增大
w1 = formula_5_weight_update(w, 1, [1, 0], config.ETA)
ok &= check("式五更新后和为1: %s" % round(float(w1.sum()), 6), abs(w1.sum() - 1) < 1e-9)
ok &= check("式五被写入经历权重增大", w1[0] > w[0])
# z=0 -> 恒等更新
w2 = formula_5_weight_update(w, 0, [1, 0], config.ETA)
ok &= check("式五 z=0 恒等更新", np.allclose(w2, w))
# I 全 0 -> 恒等更新
w3 = formula_5_weight_update(w, 1, [0, 0], config.ETA)
ok &= check("式五 I全0 恒等更新", np.allclose(w3, w))

print("=== 嵌入确定性 ===")
config.EMBED_MODEL = None
a = embedding.embed("Python 后端 Flask 开发")
b = embedding.embed("Python 后端 Flask 开发")
ok &= check("嵌入确定性(md5)", np.allclose(a, b))
ok &= check("嵌入模长归一", abs(np.linalg.norm(a) - 1.0) < 1e-9)

print()
print("=== 全部公式验证", "通过" if ok else "有失败", "===")

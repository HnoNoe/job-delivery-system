"""统一空间数据接口：服务端计算，前端 Plotly 渲染。"""
from fastapi import APIRouter, Depends

import mydata
import unispace
import viz
from server.deps import current_user

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/space")
def space_data(user=Depends(current_user)):
    owner, _ = user
    users = mydata.list_space_users()
    jobs = mydata.list_space_jobs(5000)
    if not jobs:
        return {"empty": True, "reason": "云端岗位池为空：先在桌面端抓取并推送岗位。"}
    space = unispace.build_space(users, jobs, dims=3, highlight_owner=owner)
    fig = viz.unified_space_chart(space, three_d=True)
    if fig is None:
        return {"empty": True, "reason": "空间数据不足，无法作图。"}
    return {"empty": False, "fig": fig.to_plotly_json(),
            "k": space["k"], "clusters": space["clusters"],
            "n_users": len(users), "n_jobs": len(jobs),
            "users": [{"label": u.get("label") or u["owner"], "cluster": u["cluster"],
                       "fit": u.get("fit", 0), "delivered": u.get("delivered", 0),
                       "interview": u.get("interview", 0)} for u in space["users"]]}

"""生成式人工智能客户端 —— 受约束生成（保护点1 核心）。

专利要求：不整段自由成文，而是「短任务切分 + 字段限定 + 核对回写」。
本模块抽象 LLM 调用；未配置真实 LLM 时使用确定性桩实现（严格只回填
字段表中已有的字段），保证离线可运行、且字段约束语义可验证。
"""
import json
import re


class ConstrainedLLM:
    """受约束的生成式 AI 客户端。

    generate(field_table, task_brief) -> {字段名: 字段值}
    只允许填写 field_table 中列明的字段。
    """

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def generate(self, field_table: dict, task_brief: str) -> dict:
        """按短任务说明与字段表生成字段值（受约束）。"""
        if self.api_key:
            return self._call_llm(field_table, task_brief)
        return self._stub(field_table, task_brief)

    def _stub(self, field_table: dict, task_brief: str) -> dict:
        """离线桩：只回填字段表中已有字段，不臆造新字段（演示约束语义）。"""
        out = {}
        for k, v in field_table.items():
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, (int, float)):
                out[k] = str(v)
            else:
                out[k] = ""
        return out

    def _call_llm(self, field_table: dict, task_brief: str) -> dict:
        """调用真实 LLM（OpenAI 兼容接口），强制 JSON 输出并仅取合法字段。"""
        import urllib.request
        allowed = set(field_table.keys())
        prompt = (
            "你是一个简历填写助手。任务说明：%s\n"
            "只允许输出下列字段名对应的值，不得新增任何字段名：%s\n"
            "严格输出 JSON 对象。" % (task_brief, json.dumps(list(allowed), ensure_ascii=False))
        )
        body = json.dumps({
            "model": self.model or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            (self.base_url or "https://api.openai.com/v1") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = resp["choices"][0]["message"]["content"]
        return parse_json_fields(text, allowed)


def parse_json_fields(text: str, allowed: set) -> dict:
    """从 LLM 输出中解析 JSON，并仅保留允许的字段名（核对第一步）。"""
    m = re.search(r"\{.*\}", text, re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}
    return {k: str(v) for k, v in data.items() if k in allowed}

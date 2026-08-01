"""A deliberately small learning exercise, not the production runtime.

Run with: `python docs/learning-lab/manual_loop.py`
It demonstrates the core sequence before PydanticAI adds typed model/provider support:
prompt -> model decision -> tool dispatch -> tool result -> final answer.
"""

from dataclasses import dataclass


@dataclass
class Decision:
    kind: str
    tool: str | None = None


def decide(prompt: str) -> Decision:
    if "状态" in prompt or "status" in prompt.lower():
        return Decision("tool_call", "get_status")
    return Decision("final")


def run(prompt: str) -> str:
    decision = decide(prompt)
    if decision.kind == "tool_call":
        tool_result = {"status": "online", "online_players": 2, "max_players": 20}
        return f"工具 {decision.tool} 返回：{tool_result}"
    return "没有匹配的工具请求。"


if __name__ == "__main__":
    print(run("服务器现在状态怎么样？"))

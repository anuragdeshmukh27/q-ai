"""P0 check: each model returns schema-valid JSON at an explicit num_ctx; reports tokens/s."""
import json
import sys
import time

import httpx
from pydantic import BaseModel


class Action(BaseModel):
    thought: str
    action: str
    path: str


SCHEMA = Action.model_json_schema()
PROMPT = (
    "You are a coding agent. Respond with JSON: a short thought, "
    "action 'write_file', and path 'app/main.py'."
)


def check(model: str, num_ctx: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "keep_alive": "30s",
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
    }
    t0 = time.time()
    r = httpx.post("http://localhost:11434/api/chat", json=body, timeout=300)
    wall = time.time() - t0
    r.raise_for_status()
    d = r.json()
    Action.model_validate_json(d["message"]["content"])
    tps = d["eval_count"] / (d["eval_duration"] / 1e9)
    return {"model": model, "num_ctx": num_ctx, "valid": True, "tok_s": round(tps, 1), "wall_s": round(wall, 1)}


if __name__ == "__main__":
    ctx = int(sys.argv[1]) if len(sys.argv) > 1 else 8192
    for m in ["qwen2.5-coder:7b", "qwen3:4b", "llama3.2:3b"]:
        try:
            print(json.dumps(check(m, ctx)))
        except Exception as e:
            print(json.dumps({"model": m, "valid": False, "error": str(e)[:200]}))

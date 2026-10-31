"""接口契约测试：桌宠服务升级前后都跑一遍，确保直播那边还能接。

用法（先启动服务）：
    python -m pvc
    python tests/contract.py            # 默认 http://127.0.0.1:8898
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8898"
EXPECTED_API = "1"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  通过  {name}")
    else:
        print(f"  失败  {name} {detail}")
        failures.append(name)


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print(f"契约测试目标：{BASE}")
    health = get("/health")
    check("/health ok", bool(health.get("ok")))
    check(f"/health api_version == {EXPECTED_API}", str(health.get("api_version")) == EXPECTED_API,
          f"实际 {health.get('api_version')!r}")
    check("/health 有 listening 字段", "listening" in health)
    check("/health 有 speaking 字段", "speaking" in health)

    state = get("/state")
    check("/state 有 listening/speaking", "listening" in state and "speaking" in state)

    listen = post("/listen", {"on": True})
    check("/listen 返回 listening", "listening" in listen)

    say = post("/say", {"text": "契约测试"})
    check("/say ok", bool(say.get("ok")))

    request = urllib.request.Request(
        BASE + "/say/stream", data=json.dumps({"text": "契约"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        chunk = response.read(4096)
    check("/say/stream 返回 PCM", len(chunk) > 0, f"读到 {len(chunk)} 字节")

    if failures:
        print("契约不通过：" + "、".join(failures))
        return 1
    print("契约全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

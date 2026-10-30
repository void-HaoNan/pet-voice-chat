"""大模型对话：OpenAI 兼容接口 + 人格 + 短期记忆 + 语音整理。"""

from __future__ import annotations

import json
import threading
import urllib.request


class Chat:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.history: list[dict] = []
        self._lock = threading.Lock()

    # ---------- 语音整理 ----------
    def fix_speech(self, text: str) -> str:
        """把识别结果整理成通顺口语：补标点、分句、改同音错字。失败就原样返回。"""
        cfg = self.cfg
        if not cfg.get("fix_speech", True) or not cfg.get("key"):
            return text
        system = ("你是语音整理器。把用户这句语音识别结果整理成通顺口语：补上合适的逗号、问号、句号，"
                  "改正同音错字和口误，保持原意，不要扩写、不要解释、不要加引号。只输出整理后的句子。")
        body = {"model": cfg["model"], "temperature": 0,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": text}],
                "max_tokens": 120}
        try:
            content = self._post(body)
            fixed = (content or "").strip().strip('“”"\' ')
            if fixed and 0.5 * len(text) <= len(fixed) <= 2.0 * len(text):
                return fixed
        except Exception:
            pass
        return text

    # ---------- 对话 ----------
    def reply(self, text: str) -> str:
        cfg = self.cfg
        if not cfg.get("key"):
            return "还没有配置大模型密钥，先在 config.json 的 llm.key 里填上。"
        messages = [{"role": "system", "content": cfg["persona"]}]
        with self._lock:
            messages.extend(self.history[-(int(cfg["history_turns"]) * 2):])
        messages.append({"role": "user", "content": text})
        try:
            answer = (self._post({"model": cfg["model"], "messages": messages,
                                  "max_tokens": int(cfg["max_tokens"]),
                                  "temperature": float(cfg["temperature"])}) or "").strip()
        except Exception as error:
            return f"模型这边出了点问题：{error}"
        if not answer:
            answer = "刚刚走神了，再说一遍？"
        with self._lock:
            self.history.extend([{"role": "user", "content": text},
                                 {"role": "assistant", "content": answer}])
            keep = int(cfg["history_turns"]) * 2
            if len(self.history) > keep:
                self.history = self.history[-keep:]
        return answer

    def _post(self, body: dict) -> str:
        cfg = self.cfg
        request = urllib.request.Request(
            str(cfg["base"]).rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + str(cfg["key"])},
            method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        return (data["choices"][0]["message"].get("content") or "").strip()

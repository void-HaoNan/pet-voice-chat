"""配置：默认值 + config.json + 环境变量。"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("PVC_CONFIG") or os.path.join(HERE, "config.json")

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8898,
    "asr": {
        "enabled": True,
        "vad_model": "models/silero_vad.onnx",
        "model_dir": "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "device": "",
        "sample_rate": 16000,
        "min_silence": 0.5,
        "min_speech": 0.25,
        "preroll_seconds": 0.4,
        "merge_seconds": 0.8,
        "language": "zh",
    },
    "tts": {
        "base": "http://127.0.0.1:9880",
        "ref_audio": "",
        "prompt_text": "",
        "prompt_lang": "zh",
        "text_lang": "zh",
        "streaming": True,
        "timeout": 60,
    },
    "llm": {
        "base": "https://api.deepseek.com/v1",
        "key": "",
        "model": "deepseek-chat",
        "persona": "你是一只住在电脑里的桌宠，说话短、口语化、有主见，不客套。",
        "history_turns": 8,
        "max_tokens": 200,
        "temperature": 0.8,
        "fix_speech": True,
    },
    "playback": {
        "enabled": True,
        "ffplay": "ffplay",
        "volume": 60,
    },
    # 桌宠气泡：把回复写进 say.txt，桌宠进程自己会弹出来（格式和直播那边一致）
    "bubble": {
        "enabled": True,
        "path": "%APPDATA%/dsh-pet-bubble/say.txt",
        "prio": 6,
        "ttl": 8000,
    },
}

ENV = {
    ("host",): "PVC_HOST",
    ("port",): "PVC_PORT",
    ("llm", "key"): "PVC_LLM_KEY",
    ("llm", "base"): "PVC_LLM_BASE",
    ("llm", "model"): "PVC_LLM_MODEL",
    ("tts", "base"): "PVC_TTS_BASE",
}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _apply_env(cfg: dict) -> dict:
    for path, name in ENV.items():
        value = os.environ.get(name)
        if not value:
            continue
        node = cfg
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = int(value) if path[-1] == "port" else value
    return cfg


def load() -> dict:
    data = {}
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    cfg = _apply_env(_merge(DEFAULTS, data))
    base = os.path.dirname(CONFIG_FILE)

    def abspath(value: str) -> str:
        if not value:
            return value
        return value if os.path.isabs(value) else os.path.join(base, value)

    cfg["asr"]["vad_model"] = abspath(cfg["asr"]["vad_model"])
    cfg["asr"]["model_dir"] = abspath(cfg["asr"]["model_dir"])
    cfg["tts"]["ref_audio"] = abspath(cfg["tts"]["ref_audio"])
    return cfg

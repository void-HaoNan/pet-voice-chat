"""独立自检：不依赖直播那套服务，也不出声。

覆盖三块：
1. 识别：拿一段真实人声（默认用 TTS 参考音频）跑 VAD + SenseVoice，要求识别出字、且不慢；
2. 合成：请求 /say/stream 拿 PCM，只统计字节数和首包时间，不播放、不出声；
3. 对话：直接调 Chat 问一句（有 key 才测），打印回复和耗时。

用法：
    python -m pvc                 # 另开一个窗口先起服务
    python tests/smoke.py         # 默认 http://127.0.0.1:8898
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pvc import config  # noqa: E402

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8898"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  通过  " if ok else "  失败  ") + name + ("" if ok else " " + detail))
    if not ok:
        failures.append(name)


def http_json(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def test_asr(cfg: dict) -> None:
    print("[1/3] 识别（真实人声，不出声）")
    ref = cfg["tts"].get("ref_audio") or ""
    if not ref or not os.path.isfile(ref):
        print("  跳过：没有参考音频")
        return
    import numpy as np

    from pvc.asr import build_recognizer, build_vad, transcribe

    def read_wav(path: str):
        """优先 soundfile，没有就用标准库 wave（参考音频都是 PCM wav）。"""
        try:
            import soundfile as sf
            data, rate = sf.read(path, dtype="float32", always_2d=False)
            return data, int(rate)
        except Exception:
            import wave
            with wave.open(path, "rb") as handle:
                rate = handle.getframerate()
                width = handle.getsampwidth()
                channels = handle.getnchannels()
                raw = handle.readframes(handle.getnframes())
            if width == 2:
                data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif width == 4:
                data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
            if channels > 1:
                data = data.reshape(-1, channels).mean(axis=1)
            return data, rate

    started = time.time()
    recognizer = build_recognizer(cfg["asr"])
    samples, rate = read_wav(ref)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate != int(cfg["asr"]["sample_rate"]):
        # 重采样到 16k：线性插值够用，只为了喂识别
        target = int(cfg["asr"]["sample_rate"])
        count = int(len(samples) * target / rate)
        samples = np.interp(np.linspace(0, len(samples), count, endpoint=False),
                            np.arange(len(samples)), samples).astype(np.float32)
        rate = target
    text = transcribe(recognizer, samples, rate)
    cost = time.time() - started
    check("识别出文字", bool(text), repr(text))
    check("识别耗时 < 2 秒（含加载可放宽到 6 秒）", cost < 6.0, "%.2fs" % cost)
    print("    文字：%s（%.2f 秒）" % (text or "（空）", cost))
    check("VAD 能建起来", build_vad(cfg["asr"]) is not None)


def test_tts_stream() -> None:
    print("[2/3] 合成（只统计字节，不播放）")
    body = json.dumps({"text": "这是一句自检，不出声。"}).encode("utf-8")
    request = urllib.request.Request(BASE + "/say/stream", data=body,
                                     headers={"Content-Type": "application/json"})
    started = time.time()
    first = None
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            if first is None:
                first = time.time() - started
            total += len(chunk)
    cost = time.time() - started
    check("有音频数据", total > 8000, "%d 字节" % total)
    check("首包 < 2.5 秒", first is not None and first < 2.5, "%.2fs" % (first or -1))
    print("    共 %d 字节，首包 %.2f 秒，整句 %.2f 秒" % (total, first or -1, cost))


def test_chat(cfg: dict) -> None:
    print("[3/3] 对话")
    if not cfg["llm"].get("key"):
        print("  跳过：config.json 里没填 llm.key")
        return
    from pvc.chat import Chat

    chat = Chat(cfg["llm"])
    started = time.time()
    reply = chat.reply("自检：用一句话说你现在在干什么")
    cost = time.time() - started
    check("模型有回复", bool(reply), repr(reply))
    check("回复 < 8 秒", cost < 8.0, "%.2fs" % cost)
    print("    回复：%s（%.2f 秒）" % (reply, cost))


def main() -> int:
    cfg = config.load()
    print("配置：%s" % config.CONFIG_FILE)
    try:
        health = http_json("/health")
        check("服务在线", bool(health.get("ok")), str(health))
        print("    %s" % json.dumps(health, ensure_ascii=False))
    except Exception as error:
        print("  失败  服务没起来（%s）——先 python -m pvc" % str(error)[:80])
        failures.append("服务在线")
    test_asr(cfg)
    test_tts_stream()
    test_chat(cfg)
    print()
    if failures:
        print("没通过：%s" % "、".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

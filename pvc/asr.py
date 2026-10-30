"""麦克风听写：Silero VAD 切句 + SenseVoice 识别。"""

from __future__ import annotations

import json
import os
import threading
import time

STATE = {"listening": False, "device": "", "last_error": ""}


def _sense_file(model_dir: str) -> str:
    for name in ("model.int8.onnx", "model.onnx"):
        path = os.path.join(model_dir, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"{model_dir} 里没有 SenseVoice 模型")


def build_vad(cfg: dict):
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = cfg["vad_model"]
    config.silero_vad.min_silence_duration = float(cfg["min_silence"])
    config.silero_vad.min_speech_duration = float(cfg["min_speech"])
    config.sample_rate = int(cfg["sample_rate"])
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)


def build_recognizer(cfg: dict):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=_sense_file(cfg["model_dir"]),
        tokens=os.path.join(cfg["model_dir"], "tokens.txt"),
        num_threads=2,
        language=str(cfg["language"] or "zh"),
        use_itn=True,
        provider="cpu",
    )


def transcribe(recognizer, samples, sample_rate: int) -> str:
    import numpy as np

    stream = recognizer.create_stream()
    try:
        stream.accept_waveform(sample_rate, np.asarray(samples, dtype=np.float32))
        recognizer.decode_stream(stream)
        return (stream.result.text or "").strip()
    finally:
        try:
            stream.free()
        except Exception:
            pass


class Listener:
    """一个后台线程：读麦克风 → VAD → 识别 → 回调。"""

    def __init__(self, cfg: dict, on_text, on_error=None):
        self.cfg = cfg
        self.on_text = on_text
        self.on_error = on_error or (lambda msg: None)
        self.enabled = {"on": True}
        self._busy = lambda: False
        self._thread = None
        self._stop = threading.Event()

    def set_busy_check(self, fn) -> None:
        """外部告诉它现在别听（例如桌宠正在说话）。"""
        self._busy = fn

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pvc-asr", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import numpy as np
        import sounddevice as sd

        cfg = self.cfg
        rate = int(cfg["sample_rate"])
        bench = int(rate * 0.1)
        preroll_blocks = max(1, int(float(cfg["preroll_seconds"]) / 0.1))
        merge = float(cfg["merge_seconds"])

        vad = build_vad(cfg)
        recognizer = build_recognizer(cfg)
        pending, pending_at = "", 0.0
        recent = []
        device = cfg.get("device") or None
        STATE["device"] = str(device or "默认输入设备")

        def run() -> None:
            nonlocal vad, pending, pending_at
            with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                                   blocksize=bench, device=device) as mic:
                STATE["listening"] = True
                while not self._stop.is_set():
                    data, _ = mic.read(bench)
                    if not self.enabled["on"]:
                        continue
                    samples = np.frombuffer(bytes(data), dtype=np.int16).astype(np.float32) / 32768.0
                    if self._busy():
                        vad = build_vad(cfg)
                        recent.clear()
                        continue
                    audio_blocks = list(recent)
                    vad.accept_waveform(samples)
                    recent.append(samples)
                    if len(recent) > preroll_blocks:
                        recent.pop(0)
                    while not vad.empty():
                        segment = vad.front
                        audio = np.array(segment.samples, dtype=np.float32, copy=True)
                        vad.pop()
                        if audio_blocks:
                            audio = np.concatenate([np.concatenate(audio_blocks), audio])
                        text = transcribe(recognizer, audio, rate)
                        if text:
                            pending = (pending + "，" + text) if pending else text
                            pending_at = time.time()
                    if pending and time.time() - pending_at >= merge:
                        self.on_text(pending)
                        pending = ""
                        pending_at = 0.0

        try:
            run()
        except Exception as error:
            STATE["last_error"] = str(error)
            STATE["listening"] = False
            self.on_error(f"麦克风启动失败：{error}")


def dump_devices() -> str:
    import sounddevice as sd

    return json.dumps(sd.query_devices(), ensure_ascii=False, indent=2)

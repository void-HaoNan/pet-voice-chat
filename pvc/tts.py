"""语音回复：GPT-SoVITS 流式合成，边收边播，支持插话打断。"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import urllib.request

SAMPLE_RATE = 32000
STATE = {"speaking": False}


class Speaker:
    def __init__(self, cfg: dict, on_error=None):
        self.cfg = cfg
        self.on_error = on_error or (lambda msg: None)
        self.queue: queue.Queue = queue.Queue(maxsize=8)
        self._proc = None
        self._thread = threading.Thread(target=self._worker, name="pvc-tts", daemon=True)

    def start(self) -> None:
        self._thread.start()

    # ---------- 对外 ----------
    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        try:
            self.queue.put_nowait(text)
        except queue.Full:
            self.on_error("语音队列满了，丢掉一句")

    def stop(self) -> None:
        """插话打断：停掉当前播放，清空队列。"""
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass
        STATE["speaking"] = False

    def stream_pcm(self, text: str):
        """生成器：产出 s16le PCM 字节，供别的程序自己播放。"""
        body = {
            "text": text,
            "text_lang": self.cfg["text_lang"],
            "ref_audio_path": self.cfg["ref_audio"],
            "prompt_text": self.cfg["prompt_text"],
            "prompt_lang": self.cfg["prompt_lang"],
            "streaming_mode": bool(self.cfg["streaming"]),
            "media_type": "raw",
        }
        request = urllib.request.Request(
            str(self.cfg["base"]).rstrip("/") + "/tts",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=int(self.cfg["timeout"])) as response:
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                yield chunk

    # ---------- 后台播放 ----------
    def _worker(self) -> None:
        while True:
            text = self.queue.get()
            try:
                self._play(text)
            except Exception as error:
                self.on_error(f"播放失败：{error}")

    def _play(self, text: str) -> None:
        playback = self.cfg["playback"]
        if not playback.get("enabled", True):
            for _ in self.stream_pcm(text):  # 只验证合成，不出声
                pass
            return
        command = [playback.get("ffplay", "ffplay"), "-nodisp", "-autoexit",
                   "-loglevel", "quiet", "-volume", str(int(playback.get("volume", 60))),
                   "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ch_layout", "mono", "-i", "pipe:0"]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._proc = proc
        STATE["speaking"] = True
        try:
            for chunk in self.stream_pcm(text):
                if proc.poll() is not None:
                    break
                proc.stdin.write(chunk)
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait(timeout=180)
        finally:
            if self._proc is proc:
                self._proc = None
            STATE["speaking"] = False

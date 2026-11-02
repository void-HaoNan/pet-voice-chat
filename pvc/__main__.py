"""启动：读配置、拉起听写和语音，跑本地接口。"""

from __future__ import annotations

import asyncio
import sys

from aiohttp import web

from . import config
from .asr import Listener
from .chat import Chat
from .server import Hub, build_app
from .tts import Speaker, STATE as TTS_STATE


def log(message: str) -> None:
    print(f"[pet-voice-chat] {message}", flush=True)


async def run() -> None:
    cfg = config.load()
    chat = Chat(cfg["llm"])
    # 2026-11-03：Speaker 只收 tts 段，但 _play() 要读 playback 段，
    # 少了这个键每次说话都抛 KeyError（日志「播放失败：'playback'」）。这里把两段拼一起。
    tts_cfg = dict(cfg["tts"])
    tts_cfg["playback"] = cfg.get("playback") or {}
    speaker = Speaker(tts_cfg, on_error=log)

    loop = asyncio.get_running_loop()
    listener = Listener(cfg["asr"], on_text=lambda text: asyncio.run_coroutine_threadsafe(
        hub.handle_text(text), loop), on_error=log)

    hub = Hub(cfg, listener, speaker, chat)
    # 2026-11-03：这里原来写的是 speaker.state["speaking"]，Speaker 根本没有 state 属性，
    # 听写线程第一次调 _busy() 就抛 AttributeError，表现出来就是「麦克风启动了但永远不识别」。
    listener.set_busy_check(lambda: bool(TTS_STATE.get("speaking")))
    speaker.start()
    if cfg["asr"].get("enabled", True):
        listener.start()
        log("麦克风听写已启动（VAD + SenseVoice）")
    else:
        log("麦克风已按配置关闭")

    app = build_app(hub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, cfg["host"], int(cfg["port"]))
    await site.start()
    log(f"已启动 http://{cfg['host']}:{cfg['port']} （接口见 README）")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        listener.stop()


def main() -> int:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log("已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())

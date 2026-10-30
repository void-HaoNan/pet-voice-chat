"""启动：读配置、拉起听写和语音，跑本地接口。"""

from __future__ import annotations

import asyncio
import sys

from aiohttp import web

from . import config
from .asr import Listener
from .chat import Chat
from .server import Hub, build_app
from .tts import Speaker


def log(message: str) -> None:
    print(f"[pet-voice-chat] {message}", flush=True)


async def run() -> None:
    cfg = config.load()
    chat = Chat(cfg["llm"])
    speaker = Speaker(cfg["tts"], on_error=log)

    loop = asyncio.get_running_loop()
    listener = Listener(cfg["asr"], on_text=lambda text: asyncio.run_coroutine_threadsafe(
        hub.handle_text(text), loop), on_error=log)

    hub = Hub(cfg, listener, speaker, chat)
    listener.set_busy_check(lambda: speaker.state["speaking"])
    speaker.start()
    if cfg["asr"].get("enabled", True):
        listener.start()
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

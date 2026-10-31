"""本地接口：HTTP + SSE + WebSocket。"""

from __future__ import annotations

import json
import time

from aiohttp import web, WSMsgType

from .asr import STATE as ASR_STATE
from .tts import STATE as TTS_STATE
from . import __version__

START = time.time()


class Hub:
    """把识别、对话、语音串起来，并对外广播事件。"""

    def __init__(self, cfg, listener, speaker, chat):
        self.cfg = cfg
        self.listener = listener
        self.speaker = speaker
        self.chat = chat
        self.clients: set[web.WebSocketResponse] = set()
        self.sse: set[web.StreamResponse] = set()
        self.state = {"last_text": "", "last_reply": ""}

    async def broadcast(self, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_str(payload)
            except Exception:
                self.clients.discard(ws)
        for response in list(self.sse):
            try:
                await response.write(f"data: {payload}\n\n".encode("utf-8"))
            except Exception:
                self.sse.discard(response)

    # ---------- 收到一句话 ----------
    async def handle_text(self, text: str, source: str = "mic") -> None:
        text = (text or "").strip()
        if not text:
            return
        self.speaker.stop()  # 用户开口，先停下自己
        await self.broadcast({"type": "transcript", "text": text, "source": source,
                              "ts": round(time.time(), 2)})
        cleaned = await self._in_thread(self.chat.fix_speech, text)
        reply = await self._in_thread(self.chat.reply, cleaned)
        self.state.update({"last_text": cleaned, "last_reply": reply})
        await self.broadcast({"type": "reply", "text": reply, "ts": round(time.time(), 2)})
        self.speaker.say(reply)

    @staticmethod
    async def _in_thread(fn, *args):
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def build_app(hub: Hub) -> web.Application:
    app = web.Application()

    async def health(request):
                return web.json_response({
            "ok": True, "api_version": "1", "service": "pet-voice-chat", "version": __version__,
            "listening": ASR_STATE.get("listening", False) and hub.listener.enabled["on"],
            "speaking": TTS_STATE["speaking"],
            "model": "sense-voice", "uptime": round(time.time() - START, 1),
            "last_error": ASR_STATE.get("last_error", ""),
        })

    async def state(request):
        return web.json_response({"listening": ASR_STATE.get("listening", False) and hub.listener.enabled["on"],
                                  "speaking": TTS_STATE["speaking"],
                                  "last_text": hub.state["last_text"],
                                  "last_reply": hub.state["last_reply"]})

    async def listen(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        hub.listener.enabled["on"] = bool(payload.get("on", True))
        await hub.broadcast({"type": "state", "listening": hub.listener.enabled["on"]})
        return web.json_response({"ok": True, "listening": hub.listener.enabled["on"]})

    async def say(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        text = str(payload.get("text") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text 不能为空"}, status=400)
        hub.speaker.say(text)
        return web.json_response({"ok": True, "queued": True})

    async def say_stream(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        text = str(payload.get("text") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text 不能为空"}, status=400)
        response = web.StreamResponse(headers={"Content-Type": "application/octet-stream",
                                               "Cache-Control": "no-store"})
        await response.prepare(request)
        try:
            for chunk in hub.speaker.stream_pcm(text):
                await response.write(chunk)
        except Exception:
            pass
        await response.write_eof()
        return response

    async def events(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                               "Cache-Control": "no-store",
                                               "Connection": "keep-alive"})
        await response.prepare(request)
        hub.sse.add(response)
        try:
            await response.write(b": connected\n\n")
            while True:
                await response.write(b": ping\n\n")
                await _sleep(15)
        except Exception:
            pass
        finally:
            hub.sse.discard(response)
        return response

    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        hub.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "say" and payload.get("text"):
                    hub.speaker.say(str(payload["text"]))
        finally:
            hub.clients.discard(ws)
        return ws

    app.router.add_get("/health", health)
    app.router.add_get("/state", state)
    app.router.add_post("/listen", listen)
    app.router.add_post("/say", say)
    app.router.add_post("/say/stream", say_stream)
    app.router.add_get("/events", events)
    app.router.add_get("/ws", ws_handler)
    return app


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)

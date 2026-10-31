# pet-voice-chat

桌宠实时语音聊天：本地麦克风采集、VAD 切句、本地识别、大模型对话、流式语音回复，全部在本机完成，对外只暴露一个标准的本地 HTTP + WebSocket 接口，方便别的工具（直播中台、聊天客户端、桌面宠物）接进来。

直播那套（抖音弹幕、点歌、翻唱）不在这个项目里，这里是通用的语音对话能力。

## 能力

- 麦克风实时听写：Silero VAD 切句 + SenseVoice 离线识别，自带标点和数字归一，句子完整、不吞开头
- 大模型对话：任何 OpenAI 兼容接口，带人格和短期记忆
- 流式语音回复：GPT-SoVITS 流式接口，首包约 0.6 秒，边合成边播
- 插话打断：机器人说话时你一开口就停，接着听你说
- 语音纠错：同音错字、口误、口头语先整理再交给模型
- 标准接口：别的程序通过 HTTP / WebSocket 调用，不需要改这个项目的代码

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
```

模型不在仓库里，按下面准备：

1. Silero VAD：`silero_vad.onnx`，来自 sherpa-onnx 的 asr-models 发布页
2. SenseVoice：`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`，同上下载后解压
3. GPT-SoVITS：本机跑 `api.py`，默认 9880，参考音频和参考文本填进配置

## 配置

`config.json` 里每一项都有注释，关键几项：

| 配置 | 含义 |
|---|---|
| `host` / `port` | 服务监听地址，默认 127.0.0.1:8898 |
| `asr.vad_model` | Silero VAD 模型路径 |
| `asr.model_dir` | SenseVoice 模型目录 |
| `asr.device` | 麦克风设备名，留空用系统默认 |
| `tts.base` | GPT-SoVITS 服务地址，默认 http://127.0.0.1:9880 |
| `tts.ref_audio` / `tts.prompt_text` | 音色参考音频和它的文本 |
| `llm.base` / `llm.key` / `llm.model` | 任何 OpenAI 兼容接口 |
| `llm.persona` | 人格设定 |
| `playback.enabled` | 是否真的把声音放出来，测试时可关 |

## 运行

```bash
python -m pvc
```

启动后会打印监听地址；麦克风说一句，终端和日志里就能看到识别结果和回复。

## 接口规范

所有接口都是本机回环，默认只监听 127.0.0.1。

### GET /health

```json
{"ok": true, "listening": true, "speaking": false, "model": "sense-voice", "uptime": 12.3}
```

### GET /state

```json
{"listening": true, "speaking": false, "last_text": "帮我放首歌", "last_reply": "想听什么？"}
```

### POST /listen

开关麦克风读取。

```json
{"on": true}
```

### POST /say

让桌宠说一句话，立刻返回，不等播完。

```json
{"text": "我在呢"}
```

返回 `{"ok": true, "queued": true}`。

### POST /say/stream

同一句话，但直接返回 s16le、32000Hz、单声道的 PCM 流，供播放器边收边播。适合别的程序自己接播放。

### GET /events（Server-Sent Events）

推送事件流，每行一个 JSON：

```
data: {"type":"transcript","text":"帮我放首歌","ts":1710000000.1}
data: {"type":"reply","text":"想听什么？","ts":1710000000.9}
data: {"type":"state","listening":true,"speaking":true}
```

### WS /ws

和 `/events` 同样的消息，走 WebSocket，双向：客户端也可以发 `{"type":"say","text":"..."}`。

## 给直播或其他工具接

直播中台只需要两件事：

1. 想说话：`POST /say/stream`，把 PCM 塞给 ffplay
2. 想知道主播说了什么：连 `WS /ws` 收 `transcript` 事件

直播侧只做转发，不重复实现识别和语音，两边解耦。

## 目录

```
pvc/asr.py      麦克风、VAD、SenseVoice、预录防吞字
pvc/chat.py     大模型对话、人格、短期记忆、语音整理
pvc/tts.py      GPT-SoVITS 流式合成与播放、插话打断
pvc/server.py   HTTP + WebSocket 接口
pvc/config.py   配置读取
```


## 升级与兼容

这个项目会被别的程序（比如直播中台）调用，接口变动要可预期：

1. `/health` 里带 `api_version`。接口有不兼容改动时把它加一，别偷改字段含义。
2. 调用方启动或调用前先读 `api_version`，对不上就退回自己的实现，不要硬调。
3. 项目自带接口契约测试，任何改动前后都跑一遍：

```bash
python tests/contract.py                # 默认连 127.0.0.1:8898
python tests/contract.py http://127.0.0.1:8898
```

全部通过才算没破坏兼容；要加新能力就加新接口，旧的保留一个版本再删。

## 常见问题

- 识别吞字：`asr.preroll_seconds` 调到 0.5，VAD 判定前的 0.4 秒会一起送进识别
- 延迟高：先看 `tts.streaming` 是否为 true，再看 GPT-SoVITS 是否开了流式
- 没声音：`playback.enabled` 是否为 true，`playback.ffplay` 是否在 PATH 里
- 麦克风听不到：换 `asr.device`，先用 `python -c "import sounddevice; print(sounddevice.query_devices())"` 看设备名

## 许可

MIT

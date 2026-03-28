# AI助手（Python 项目骨架）

## 1. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. 配置环境变量

复制 `.env.example` 为 `.env` 并按需修改：

```env
HOST=0.0.0.0
PORT=8765
DEBUG=true
WS_TOKEN=replace_with_your_ws_token
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_API_KEY=
ARK_MODEL=doubao-pro-32k
TEMPERATURE_DEFAULT=0.6
TEMPERATURE_FACTUAL=0.2
TEMPERATURE_CHAT=0.9
NETEASE_API_URL=http://127.0.0.1:3000
NETEASE_COOKIE=
NETEASE_USER_ID=
NETEASE_FAVORITE_PLAYLIST_ID=
REQUEST_TIMEOUT_SECONDS=15
QWEATHER_API_KEY=
QWEATHER_API_HOST=
QWEATHER_GEO_BASE_URL=https://geoapi.qweather.com/v2
QWEATHER_WEATHER_BASE_URL=https://devapi.qweather.com/v7
TTS_VOICE=zh-CN-XiaoxiaoNeural
TTS_RATE=+0%
TTS_VOLUME=+0%
TTS_PROVIDER=edge
TTS_VOLC_BASE_URL=
TTS_VOLC_VOICE_TYPE=BV001_streaming
TTS_VOLC_CLUSTER=volcano_tts
TTS_VOLC_ENCODING=mp3
TTS_VOLC_SPEED_RATIO=1.0
TTS_VOLC_VOLUME_RATIO=1.0
TTS_VOLC_PITCH_RATIO=1.0
TTS_VOLC_AUTH_STYLE=auto
LOG_LEVEL=INFO
VOLC_APP_ID=
VOLC_ACCESS_TOKEN=
VOLC_SECRET_KEY=
VOLC_ASR_WS_URL=wss://openspeech.bytedance.com/api/v2/asr
VOLC_TTS_WS_URL=wss://openspeech.bytedance.com/api/v3/tts/bidirection
ASR_PROVIDER=openai
ASR_BASE_URL=https://api.openai.com/v1/audio/transcriptions
ASR_API_KEY=
ASR_APP_ID=
ASR_ACCESS_TOKEN=
ASR_SECRET_KEY=
ASR_AUTH_STYLE=auto
ASR_MODEL=whisper-1
ASR_LANGUAGE=zh
ASR_MAX_AUDIO_BYTES=10485760
```

火山模式示例：
- `ASR_PROVIDER=volc`（或 `volcengine`），并配置 `ASR_BASE_URL` + `ASR_APP_ID/ASR_ACCESS_TOKEN`（或复用 `VOLC_APP_ID/VOLC_ACCESS_TOKEN`）。
- `ASR_AUTH_STYLE=token` 会自动映射为火山 `Bearer; token` 头格式。
- `TTS_PROVIDER=volc`（或 `volcengine`），并配置 `TTS_VOLC_BASE_URL`（可填 `wss://...`）+ `VOLC_APP_ID/VOLC_ACCESS_TOKEN`。
- `TTS_VOLC_AUTH_STYLE` 支持 `auto/token`（映射为 `Bearer; token`）或 `bearer`（映射为 `Bearer token`）。

## 3. 知识库（外部定时写入，可选）

- 配置见 `.env.example` 中 `KNOWLEDGE_*`；**`KNOWLEDGE_HTTP_PORT=0` 时默认不开放 HTTP**。
- 开启后写入地址：`http://<HOST>:<PORT>/v1/knowledge/ingest`（需 `Bearer` 或 `X-Knowledge-Token`）。
- 完整说明与 curl 示例：[`docs/knowledge-ingest-api.md`](docs/knowledge-ingest-api.md)。

## 4. 启动服务

```bash
python main.py
```

启动成功后，你可以用任意 WebSocket 客户端连接 `ws://HOST:PORT` 进行测试。

## 5. WebSocket 协议（最小可用）

客户端发送 `AUTH`（当 `WS_TOKEN` 非空时必须先鉴权）：

```json
{
  "type": "AUTH",
  "trace_id": "demo-auth",
  "payload": {
    "token": "replace_with_your_ws_token"
  }
}
```

心跳：

```json
{
  "type": "PING",
  "trace_id": "demo-ping",
  "payload": {}
}
```

发送文本指令：

```json
{
  "type": "TEXT",
  "trace_id": "demo-text",
  "payload": {
    "text": "这首歌好听"
  }
}
```

服务端会返回 `TEXT`、`TOOL_RESULT`，在点红心成功时额外返回 `EFFECT`（`HEART`）。
当工具触发网易云登录二维码时，额外返回 `QRCODE`；当工具触发播放时，额外返回 `AUDIO_URL`。
当工具触发天气查询时，额外返回 `WEATHER_CARD`（含 3 天预报）。
天气工具除了普通天气外，也支持“几点几分下雨”“未来一小时会不会下雨”“雨什么时候停”“要不要带伞”等分钟级降水问法。
当服务端启用 TTS 时，还会推送 `AUDIO_CHUNK` + `AUDIO_END`。
当识别到“换成/切换”类指令时，会推送 `MODEL_SWITCH`。
当发送音频输入时，服务端会返回 `ASR_RESULT` 并继续走对话链路。

音频输入事件示例（base64 分片）：
```json
{
  "type": "AUDIO_INPUT_CHUNK",
  "trace_id": "audio-1",
  "payload": {
    "chunk_base64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEA..."
  }
}
```

音频输入结束事件：
```json
{
  "type": "AUDIO_INPUT_END",
  "trace_id": "audio-1",
  "payload": {}
}
```

## 6. 搜索选歌多轮示例

1. 发送：`TEXT: 播放 稻香`
2. 服务端返回多个候选时，会在 `TEXT` 中提示“第几首”
3. 再发送：`TEXT: 第2首`
4. 服务端触发 `play_music`，返回 `TOOL_RESULT`，并推送 `AUDIO_URL`

## 7. 平板联调页面

已提供最小前端联调页：`web-client/index.html`。

- 方式一：直接在浏览器打开 `web-client/index.html`
- 方式二：通过静态服务器访问（推荐）

页面已内置以下消息处理：
- `TEXT`：显示 AI 回复
- `QRCODE`：展示网易云登录二维码
- `AUDIO_URL`：设置播放器并自动尝试播放
- `AUDIO_CHUNK` / `AUDIO_END`：分片音频接收与播放
- `ASR_RESULT`：显示语音转写结果
- `EFFECT`：目前支持 `HEART` 动效
- `WEATHER_CARD`：展示 3 天天气卡片；语音文本同时可回答分钟级降水与停雨时间
- `MODEL_SWITCH`：加载并切换 Live2D 模型
- `TOOL_RESULT` / `ERROR`：写入日志面板

页面还提供了“发送音频输入（AUDIO_INPUT）”功能，可直接上传本地音频文件，验证 ASR -> 对话 -> TTS 全链路。

## 8. 老安卓兼容构建（Babel）

在 `web-client/` 下执行：
- `npm install`
- `npm run build`

构建后会生成 `web-client/dist/js` 目录，用于老旧 WebView 的 JS 兼容版本。

## 9. 非 Docker 部署

已提供 systemd 服务模板与部署文档：
- 服务文件：`scripts/systemd/ai-assistant.service`、`scripts/systemd/netease-api.service`、`scripts/systemd/xiaozhi-server.service`
- 部署说明：`部署说明-systemd.md`

网易云 API 说明：
- 原始 `Binaryify/NeteaseCloudMusicApi` GitHub 仓库已不再维护代码。
- 当前建议使用 `@neteasecloudmusicapienhanced/api` npm 包部署方式（文档已同步）。

## 10. 任务1.2（小智后端 + 豆包 + 火山引擎 ASR/TTS）

**方案定型：ASR/TTS 全部使用火山引擎云 API，拒绝本地模型（FunASR / GPT-SoVITS 等）。**

已补充交付文件：
- `scripts/systemd/xiaozhi-server.service`（源码部署的 systemd 托管模板）
- `scripts/xiaozhi/.config.yaml.doubao.example`（豆包 LLM + DoubaoASR + 火山流式 TTS 配置模板）
- `scripts/xiaozhi/.config.yaml.volc-api-only.example`（全 API 方案最小可用配置，带注释说明）
- `scripts/xiaozhi/deploy-xiaozhi-linux.sh`（Linux 一键生成含火山 ASR/TTS 配置的脚本）
- `任务1.2-小智后端与豆包接入.md`（完整执行说明与验收清单，v2.0）

## 11. 任务1.3（智控台后台管理页面）

**小智开源 Admin 后台（智控台）部署方案，支持：设备管理、OTA 升级、配置管理、多用户。**

- 部署方式：Docker 全模块安装（含 MySQL、Redis、Java Web、Python Server）
- 访问地址：`http://服务器IP:8002`（部署完成后）
- 配置 ASR/TTS 直接在智控台界面操作，无需手动改配置文件

详细步骤见：`任务1.3-智控台部署与接入指南.md`

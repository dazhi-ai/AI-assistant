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
QWEATHER_GEO_BASE_URL=https://geoapi.qweather.com/v2
QWEATHER_WEATHER_BASE_URL=https://devapi.qweather.com/v7
TTS_VOICE=zh-CN-XiaoxiaoNeural
TTS_RATE=+0%
TTS_VOLUME=+0%
LOG_LEVEL=INFO
```

## 3. 启动服务

```bash
python main.py
```

启动成功后，你可以用任意 WebSocket 客户端连接 `ws://HOST:PORT` 进行测试。

## 4. WebSocket 协议（最小可用）

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
当服务端启用 TTS 时，还会推送 `AUDIO_CHUNK` + `AUDIO_END`。
当识别到“换成/切换”类指令时，会推送 `MODEL_SWITCH`。

## 5. 搜索选歌多轮示例

1. 发送：`TEXT: 播放 稻香`
2. 服务端返回多个候选时，会在 `TEXT` 中提示“第几首”
3. 再发送：`TEXT: 第2首`
4. 服务端触发 `play_music`，返回 `TOOL_RESULT`，并推送 `AUDIO_URL`

## 6. 平板联调页面

已提供最小前端联调页：`web-client/index.html`。

- 方式一：直接在浏览器打开 `web-client/index.html`
- 方式二：通过静态服务器访问（推荐）

页面已内置以下消息处理：
- `TEXT`：显示 AI 回复
- `QRCODE`：展示网易云登录二维码
- `AUDIO_URL`：设置播放器并自动尝试播放
- `AUDIO_CHUNK` / `AUDIO_END`：分片音频接收与播放
- `EFFECT`：目前支持 `HEART` 动效
- `WEATHER_CARD`：展示 3 天天气卡片
- `MODEL_SWITCH`：加载并切换 Live2D 模型
- `TOOL_RESULT` / `ERROR`：写入日志面板

## 7. 老安卓兼容构建（Babel）

在 `web-client/` 下执行：
- `npm install`
- `npm run build`

构建后会生成 `web-client/dist/js` 目录，用于老旧 WebView 的 JS 兼容版本。

## 8. 非 Docker 部署

已提供 systemd 服务模板与部署文档：
- 服务文件：`scripts/systemd/ai-assistant.service`、`scripts/systemd/netease-api.service`
- 部署说明：`部署说明-systemd.md`

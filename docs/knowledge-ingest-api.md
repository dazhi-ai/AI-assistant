# 知识库 HTTP 写入接口

## 现状说明

- 本仓库 **原先没有** 独立「知识库」服务；现已在本机 **AI 助手后端**（`main.py` / `src/server.py`）上增加 **可选的 HTTP 写入接口**。
- 数据落在 **`KNOWLEDGE_DATA_PATH`**（默认 `data/knowledge_base.jsonl`），每行一条 JSON。
- 对话时会把文件中 **最近若干条** 拼进 **system prompt**（长度上限由 `KNOWLEDGE_CONTEXT_MAX_CHARS` 控制）。**不是向量检索**，适合外部定时同步短文、公告、运维说明等。

## 启用方式

在 `.env` 中配置：

```env
# 监听端口，0 表示不启动 HTTP（仍可手动编辑 jsonl，模型仍会读）
KNOWLEDGE_HTTP_PORT=8770
# 写入密钥，务必足够长且保密；仅通过 HTTPS 反向代理对外暴露
KNOWLEDGE_INGEST_TOKEN=your_long_random_secret
# 可选
KNOWLEDGE_DATA_PATH=data/knowledge_base.jsonl
KNOWLEDGE_CONTEXT_MAX_CHARS=6000
```

启动后日志会打印：

- `Knowledge ingest URL: http://<HOST>:<PORT>/v1/knowledge/ingest`

公网使用时请用 **Nginx/Caddy** 反代到 `https://你的域名/knowledge/...` 并限制来源 IP（可选）。

## 写入地址（对外给「别人的服务器」用）

| 方法 | 路径 | 鉴权 |
|------|------|------|
| `POST` | `http://<你的服务器IP或域名>:8770/v1/knowledge/ingest` | 见下 |
| `GET` | `http://<你的服务器IP或域名>:8770/v1/knowledge/health` | 无（健康检查） |

鉴权（二选一）：

- `Authorization: Bearer <KNOWLEDGE_INGEST_TOKEN>`
- `X-Knowledge-Token: <KNOWLEDGE_INGEST_TOKEN>`

## 请求体（JSON）

| 字段 | 必填 | 说明 |
|------|------|------|
| `content` | 是 | 正文（纯文本或 Markdown） |
| `title` | 否 | 标题 |
| `source` | 否 | 来源标识（如对方服务器名、任务名） |
| `tags` | 否 | 字符串数组 |

**示例：**

```bash
curl -sS -X POST "http://127.0.0.1:8770/v1/knowledge/ingest" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_long_random_secret" \
  -d '{"title":"公告","content":"今日维护窗口 02:00-03:00","source":"cron-server-1","tags":["ops"]}'
```

**成功响应：**

```json
{"ok": true, "id": "十六进制uuid", "stored_at": "2026-03-22T12:00:00+00:00"}
```

## 安全建议

1. **不要** 在无 TLS 的公网明文传 Token；务必 **HTTPS + 强随机 Token**。
2. 在反代层加 **IP 白名单** 或 **mTLS**（若对方为固定机位）。
3. 定期轮转 `KNOWLEDGE_INGEST_TOKEN`；旧 Token 失效后更新对方定时任务配置。

## 与小智 ESP32 服务器的关系

若你实际对话走的是 **xiaozhi-esp32-server**，其「记忆/知识库」为 **另一套实现**，与本仓库 HTTP 接口 **不自动打通**。

**若外部注入的知识是给「小智聊天」用的，应走小智服务端 + 智控台维护**（而非本接口）。说明见：[`xiaozhi-knowledge-vs-local-ingest.md`](xiaozhi-knowledge-vs-local-ingest.md)。

本接口主要服务 **本仓库 `python main.py` 启动的 WebSocket AI 助手后端**。

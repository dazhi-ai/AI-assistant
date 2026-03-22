# 火山双流 TTS：按消息携带的 sentence_id 启停会话

网易云插件为音乐单独生成 `music_sid` 并写入每条 `TTSMessageDTO`。  
原版 `huoshan_double_stream.py` 的 `tts_text_priority_thread` **忽略** `message.sentence_id`，始终用 `conn.sentence_id`，会导致：

1. 框架 `LAST(A)` 在插件改写 `conn.sentence_id` 后错误地 `finish_session(错误id)`；
2. 音乐 session 与豆包侧状态不一致，`EVENT_SessionFinished` 对不上，`_process_before_stop_play_files` 不触发 → **无声**。

## 修改点（`tts_text_priority_thread` 内）

### FIRST 分支

在 `if not getattr(self.conn, "sentence_id", None):` 之前增加：

```python
                        if getattr(message, "sentence_id", None):
                            self.conn.sentence_id = message.sentence_id
                        elif not getattr(self.conn, "sentence_id", None):
```

（原 `if not getattr` 改为 `elif not getattr`。）

### LAST 分支

将 `self.finish_session(self.conn.sentence_id)` 改为：

```python
                        finish_sid = getattr(message, "sentence_id", None) or self.conn.sentence_id
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(finish_sid),
```

部署后需与 `play_music_netease.py`（使用 `music_sid`、不提前改 `conn.sentence_id`）一起生效。

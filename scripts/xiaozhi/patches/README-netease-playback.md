# 网易云直连播放与流控说明

## 单曲循环 `single_loop`

工具参数 **`single_loop: true`** 时，当前这一首在整段 Opus 入队并**按估算时长（帧数×60ms+间隔）**结束后，会**自动再次入队**同一首，直到：

- 用户再次触发 `play_music`（新任务会递增 `netease_loop_generation`，旧循环退出），或  
- `client_abort` 为真（防打断窗口过后用户打断），或  
- 连接断开。

大模型需在用户说「单曲循环」「一直放这首」等时把 `single_loop` 设为 `true`。

**注意**：单曲循环时，防打断窗口会按 **本首估算播放时长 + 缓冲** 拉长（而不仅是 15 秒），否则长歌播到十几秒时设备仍可能发 `abort`，服务端清空队列后 `client_abort` 会令循环任务误判退出。

## 播歌防打断与「唤醒词优先」（单曲循环可打断）

插件在直连音乐**全部写入** `tts_audio_queue` 后，会设置 `conn.netease_music_shield_until`（普通播放约 **15 秒**；单曲循环为**整首估算时长 + 缓冲**）。

在防打断窗口内：

- **VAD 触发的 abort**（`receiveAudioHandle.handleAudioMessage`）：仍**忽略**，避免误触断播。  
- **明确唤醒词**（`listen` → `detect` 且文案命中 `wakeup_words`，经 `startToChat(..., from_wake_word=True)`）：**解除窗口、取消单曲循环后台任务**，并正常 `clear_queues` / `tts stop`；用户**下一句非唤醒语音**在助理播报结束后，会**多播一句**询问是否继续单曲循环（说「继续播放」等可由大模型再调 `play_music`）。

须同时部署本目录下：

| 文件 | 容器内路径 |
|------|------------|
| `abortHandle.py` | `core/handle/abortHandle.py` |
| `receiveAudioHandle.py` | `core/handle/receiveAudioHandle.py` |
| `listenMessageHandler.py` | `core/handle/textHandler/listenMessageHandler.py` |
| `../plugins_func/functions/play_music_netease.py` | `plugins_func/functions/play_music.py`（或你实际挂载的 play_music 文件名） |

部署示例（路径按你环境调整）：

```bash
scp -P 1258 abortHandle.py receiveAudioHandle.py listenMessageHandler.py root@HOST:/tmp/
scp -P 1258 ../plugins_func/functions/play_music_netease.py root@HOST:/tmp/play_music.py
ssh -p 1258 root@HOST "docker cp /tmp/abortHandle.py xiaozhi-esp32-server:/opt/xiaozhi-esp32-server/core/handle/abortHandle.py && \
  docker cp /tmp/receiveAudioHandle.py xiaozhi-esp32-server:/opt/xiaozhi-esp32-server/core/handle/receiveAudioHandle.py && \
  docker cp /tmp/listenMessageHandler.py xiaozhi-esp32-server:/opt/xiaozhi-esp32-server/core/handle/textHandler/listenMessageHandler.py && \
  docker cp /tmp/play_music.py xiaozhi-esp32-server:/opt/xiaozhi-esp32-server/plugins_func/functions/play_music.py && \
  docker exec xiaozhi-esp32-server find /opt/xiaozhi-esp32-server -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; \
  docker restart xiaozhi-esp32-server"
```

## 若「口播正常、音乐仍无声」

小智 `sendAudioHandle` 用 `conn.sentence_id` 与 `audio_flow_control["sentence_id"]` 判断是否**复用**同一句的流控。  
火山 TTS 结束后 `conn.sentence_id` 仍是本次 `music_sid` 时，直连音乐的 `FIRST` 会误走 `add_message(sentence_start)`，与上一会话流控串台。

**插件已处理**：下发音乐前执行 `conn.sentence_id = uuid.uuid4().hex`，强制重置 `AudioRateController`。

## 若日志出现 `等待超时 phase=2，放弃下发`

表示已进入网易云 TTS 会话（`activate_session` 曾为 True），但长时间内**未收到**火山侧会话结束
（`activate_session` 一直为 True）。常见原因：`EVENT_SessionFinished` 未到达、`finish_session` 失败等。  

**插件已处理**：phase2 超过约 **35 秒**仍不结束时，会打警告日志并**强制编码下发**，避免无声死等 120 秒。

## 若日志出现 `[直连音乐] 用户打断，取消播放`

防打断窗口**之外**的 **abort** 仍会结束单曲循环任务。若已部署「唤醒词优先」补丁，在窗口内说**唤醒词**会主动取消循环并清空队列，而**非唤醒的 VAD abort** 在窗口内仍被忽略。

## 不要改 `base._process_before_stop_play_files` 空列表仍发 LAST

空列表时的 `LAST` 会触发客户端 `tts stop`，结束口播会话；若去掉可能导致设备一直认为 TTS 未结束。

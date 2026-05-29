"""
小智服务端 abort 处理（带网易云播歌防打断 + 唤醒词优先打断单曲循环）

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/abortHandle.py
然后删除对应 __pycache__ 并 restart 容器。

逻辑（分层防打断）：
0. Tier1 绝对防打断：音乐首帧尚未下行(netease_music_wait_first_downlink) 或 首帧下行后未满
   netease_music_hard_block_until（约 3s）——仅忽略「非唤醒」abort（VAD/噪声）。
   唤醒词 abort 绝不在此拦截：设备固件一旦本地识别到唤醒词即停止播放并进入聆听，服务端若忽略
   会与设备状态错位 → 死锁、口令失灵，故唤醒词始终放行、立即打断。
1. Tier2 播歌防打断窗口（conn.netease_music_shield_until，覆盖整首估算时长）：
   - 非唤醒 abort（VAD/噪声）：忽略，防误触断播（只认口令打断）；
   - 唤醒 abort：单次唤醒词随时即可打断/换歌。
2. 真正打断（窗口外，或防打断窗口内的唤醒词）：
   - 解除防打断窗口；
   - 清除 conn.netease_music_hold_listen_until_wake，使播歌结束后可再次正常响应 listen start；
   - 若存在单曲循环快照（conn.netease_resume_snapshot），递增 netease_loop_generation 停止后台循环，
     并置 netease_resume_prompt_armed，便于用户下一句非唤醒指令说完后播报「是否继续播放」。
3. 其它与官方一致：client_abort、clear_queues、tts stop。
"""

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


async def handleAbortMessage(conn: "ConnectionHandler", from_wake_word: bool = False):
    now = time.monotonic()

    # ── Tier 1：绝对防打断窗口（仅对非唤醒 abort 生效）──
    # 音乐首帧尚未真正下行（wait_first_downlink），或首帧下行后未满 hard_block 秒，期间忽略
    # 非唤醒（VAD/噪声）abort，保证「找到歌曲后直接播放」且有最短稳定播放时长。
    # 注意：唤醒词 abort 绝不在此拦截——设备固件一旦本地识别到唤醒词会立即停止播放并进入聆听，
    # 服务端若「忽略」该 abort 会与设备状态错位（设备已停播在听、服务端仍发帧不响应）→ 死锁、口令失灵
    # （线上 19:22「落(花开花落)」复现：唤醒落在 3s 窗口末 0.3s 被忽略后整段无响应）。故唤醒词始终放行。
    hard_until = getattr(conn, "netease_music_hard_block_until", 0.0)
    try:
        hard_until = float(hard_until)
    except (TypeError, ValueError):
        hard_until = 0.0
    hard_active = (hard_until > 0.0 and now < hard_until) or bool(
        getattr(conn, "netease_music_wait_first_downlink", False)
    )
    if hard_active and not from_wake_word:
        conn.logger.bind(tag=TAG).info(
            "网易云绝对防打断窗口内，忽略本次非唤醒 abort；"
            f"剩余约 {max(0.0, hard_until - now):.1f}s"
        )
        return

    # ── Tier 2：播歌防打断窗口 ──
    shield_until = getattr(conn, "netease_music_shield_until", 0.0)
    try:
        shield_until = float(shield_until)
    except (TypeError, ValueError):
        shield_until = 0.0
    now_shielded = shield_until > 0.0 and now < shield_until

    if now_shielded:
        remaining = shield_until - now
        if not from_wake_word:
            # 非唤醒（VAD/环境噪声）：整首播放期间忽略，避免噪声误打断（只认口令打断）
            conn.logger.bind(tag=TAG).info(
                f"播歌防打断窗口内，忽略非唤醒 abort（剩余约 {max(0.0, remaining):.1f}s）"
            )
            return
        # 唤醒词：3 秒绝对防打断窗口已过，单次唤醒即可打断/换歌（落到下方正式打断流程）
        conn.logger.bind(tag=TAG).info(
            f"播歌中收到唤醒词，单次唤醒即打断（防打断窗口剩余约 {max(0.0, remaining):.1f}s，唤醒优先）"
        )

    if from_wake_word and now_shielded:
        conn.netease_music_shield_until = 0.0
        conn.logger.bind(tag=TAG).info("唤醒词：已解除播歌防打断窗口")

    if from_wake_word:
        # 允许设备在唤醒后正常走 listen start → reset_audio_states（播歌挂起聆听）
        conn.netease_music_hold_listen_until_wake = False
        snap = getattr(conn, "netease_resume_snapshot", None)
        if isinstance(snap, dict) and snap.get("single_loop"):
            prev = int(getattr(conn, "netease_loop_generation", 0))
            conn.netease_loop_generation = prev + 1
            conn.netease_resume_prompt_armed = True
            conn.logger.bind(tag=TAG).info(
                "唤醒词：已取消单曲循环后台任务；您下一句指令说完后会询问是否继续播放"
            )

    conn.logger.bind(tag=TAG).info("Abort message received")
    conn.client_abort = True
    conn.clear_queues()
    await conn.websocket.send(
        json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id})
    )
    conn.clearSpeakStatus()

    # 彻底关闭 TTS 引擎到火山的 WebSocket 连接。
    # abort 后旧连接可能处于脏状态（会话未正常结束），若被下一次"使用已有链接"
    # 复用，新 TTS 会话将无法生成语音，导致 _enqueue_music_opus_direct 在 phase2
    # 空等超时后才强制下发音乐（用户感知为长时间卡在"聆听中"）。
    # close() 会重置 activate_session、取消 monitor 任务、关闭 WS，
    # 下一次 TTS 调用将经 _ensure_connection 建立全新连接。
    tts = getattr(conn, "tts", None)
    if tts is not None:
        try:
            await tts.close()
            conn.logger.bind(tag=TAG).info("已关闭 TTS 引擎连接，下次将建立新连接")
        except Exception as e:
            conn.logger.bind(tag=TAG).warning(f"关闭 TTS 引擎连接时异常: {e}")

    conn.logger.bind(tag=TAG).info("Abort message received-end")

"""
小智服务端 abort 处理（带网易云播歌防打断 + 唤醒词优先打断单曲循环）

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/abortHandle.py
然后删除对应 __pycache__ 并 restart 容器。

逻辑：
1. 播歌后一段时间内（conn.netease_music_shield_until）忽略**非唤醒**的 abort，防误触断播。
2. 若本次 abort 来自**明确唤醒词**（listen detect → startToChat 传入 from_wake_word=True）：
   - 解除防打断窗口；
   - 若当前存在单曲循环快照（conn.netease_resume_snapshot），递增 netease_loop_generation 以停止后台循环，
     并置 netease_resume_prompt_armed，便于用户下一句非唤醒指令说完后播报「是否继续播放」。
3. 其它情况与官方一致：client_abort、clear_queues、tts stop。
"""

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


async def handleAbortMessage(conn: "ConnectionHandler", from_wake_word: bool = False):
    shield_until = getattr(conn, "netease_music_shield_until", 0.0)
    try:
        shield_until = float(shield_until)
    except (TypeError, ValueError):
        shield_until = 0.0
    now_shielded = shield_until > 0.0 and time.monotonic() < shield_until

    if now_shielded and not from_wake_word:
        remaining = shield_until - time.monotonic()
        conn.logger.bind(tag=TAG).info(
            f"播歌防打断窗口内，忽略本次 abort（剩余约 {max(0.0, remaining):.1f}s）"
        )
        return

    if from_wake_word and now_shielded:
        conn.netease_music_shield_until = 0.0
        conn.logger.bind(tag=TAG).info("唤醒词：已解除播歌防打断窗口")

    if from_wake_word:
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

"""
小智服务端 abort 处理（带网易云播歌防打断）

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/abortHandle.py
然后删除对应 __pycache__ 并 restart 容器。

逻辑：plugins_func.functions.play_music_netease 在直连音乐全部入队后会设置
  conn.netease_music_shield_until = time.monotonic() + 15
在此时间之前收到的 abort（含 wake_word_detected）将被忽略，避免误触断播。
"""

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


async def handleAbortMessage(conn: "ConnectionHandler"):
    # ---------- 网易云播歌防打断（与 play_music_netease.NETEASE_MUSIC_ANTI_INTERRUPT_SEC 配合）----------
    shield_until = getattr(conn, "netease_music_shield_until", 0.0)
    try:
        shield_until = float(shield_until)
    except (TypeError, ValueError):
        shield_until = 0.0
    if shield_until > 0.0 and time.monotonic() < shield_until:
        remaining = shield_until - time.monotonic()
        conn.logger.bind(tag=TAG).info(
            f"播歌防打断窗口内，忽略本次 abort（剩余约 {max(0.0, remaining):.1f}s）"
        )
        return
    # ----------------------------------------------------------------------------------------------

    conn.logger.bind(tag=TAG).info("Abort message received")
    # 设置成打断状态，会自动打断llm、tts任务
    conn.client_abort = True
    conn.clear_queues()
    # 打断客户端说话状态
    await conn.websocket.send(
        json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id})
    )
    conn.clearSpeakStatus()
    conn.logger.bind(tag=TAG).info("Abort message received-end")

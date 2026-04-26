"""
与官方 abortMessageHandler 对齐；增加对 abort 消息中 reason="wake_word_detected" 的识别，
将其作为唤醒词打断传递给 handleAbortMessage，使单曲循环防打断窗口内仍能响应唤醒词。

日志表明播歌期间设备常连发 wake_word_detected（歌词/噪声误触），每次都会清 hold → listen 未抑制。
在「口播排播 expect_delivery」或「首帧后防打断 shield」窗口内对 wake abort 做短时防抖，保留首次、抑制过密连发。

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/textHandler/abortMessageHandler.py
"""

import time
from typing import Dict, Any

from core.handle.abortHandle import handleAbortMessage
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType

TAG = __name__
# 与播歌口播/首包 shield 窗口对齐：过密的 wake_word_detected 视为误触（见线上 16:34～16:36 连发 abort）
_NETEASE_WAKE_ABORT_DEBOUNCE_SEC = 1.5


class AbortTextMessageHandler(TextMessageHandler):

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.ABORT

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        reason = msg_json.get("reason", "")
        is_wake = reason == "wake_word_detected"
        if is_wake:
            now = time.monotonic()
            in_expect = bool(getattr(conn, "netease_music_expect_delivery", False))
            in_shield = False
            try:
                su = float(getattr(conn, "netease_music_shield_until", 0.0) or 0.0)
                in_shield = su > 0.0 and now < su
            except (TypeError, ValueError):
                pass
            if in_expect or in_shield:
                last = float(getattr(conn, "_netease_wake_abort_debounce_at", 0.0) or 0.0)
                if last > 0.0 and (now - last) < _NETEASE_WAKE_ABORT_DEBOUNCE_SEC:
                    conn.logger.bind(tag=TAG).info(
                        f"网易云排播/防打断窗口：wake_word_detected 过密（{now - last:.2f}s），防抖忽略"
                    )
                    return
                conn._netease_wake_abort_debounce_at = now
        await handleAbortMessage(conn, from_wake_word=is_wake)

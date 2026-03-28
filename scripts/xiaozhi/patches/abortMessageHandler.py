"""
与官方 abortMessageHandler 对齐；增加对 abort 消息中 reason="wake_word_detected" 的识别，
将其作为唤醒词打断传递给 handleAbortMessage，使单曲循环防打断窗口内仍能响应唤醒词。

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/textHandler/abortMessageHandler.py
"""

from typing import Dict, Any

from core.handle.abortHandle import handleAbortMessage
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType


class AbortTextMessageHandler(TextMessageHandler):

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.ABORT

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        reason = msg_json.get("reason", "")
        is_wake = reason == "wake_word_detected"
        await handleAbortMessage(conn, from_wake_word=is_wake)

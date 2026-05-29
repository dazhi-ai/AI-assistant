"""
与官方 abortMessageHandler 对齐；增加对 abort 消息中 reason="wake_word_detected" 的识别，
将其作为唤醒词打断传递给 handleAbortMessage。

播歌期间设备常误报 wake_word_detected（疑似把正在播放的音乐误识别为唤醒词），由
handleAbortMessage 统一做分层防打断处理（首帧后 3s 绝对忽略 + 整首窗口内「二次唤醒确认」才打断），
故此处只负责识别 reason 并透传，不再自行做防抖（避免吞掉「二次唤醒确认」所需的第二次唤醒）。

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/textHandler/abortMessageHandler.py
"""

from typing import Dict, Any

from core.handle.abortHandle import handleAbortMessage
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType

TAG = __name__


class AbortTextMessageHandler(TextMessageHandler):

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.ABORT

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        reason = msg_json.get("reason", "")
        is_wake = reason == "wake_word_detected"
        await handleAbortMessage(conn, from_wake_word=is_wake)

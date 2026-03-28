"""
与官方 listenMessageHandler 对齐；唤醒词路径调用 startToChat(..., from_wake_word=True)，
以便 abortHandle 在单曲循环防打断窗口内仍能优先响应唤醒。

部署：覆盖容器内
  /opt/xiaozhi-esp32-server/core/handle/textHandler/listenMessageHandler.py
"""

import time
import asyncio
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

from core.handle.abortHandle import handleAbortMessage
from core.handle.receiveAudioHandle import startToChat
from core.handle.reportHandle import enqueue_asr_report
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.util import remove_punctuation_and_length
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__


class ListenTextMessageHandler(TextMessageHandler):
    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.LISTEN

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        if "mode" in msg_json:
            conn.client_listen_mode = msg_json["mode"]
            conn.logger.bind(tag=TAG).debug(
                f"客户端拾音模式：{conn.client_listen_mode}"
            )
        if msg_json["state"] == "start":
            conn.reset_audio_states()
        elif msg_json["state"] == "stop":
            conn.client_voice_stop = True
            if conn.asr.interface_type == InterfaceType.STREAM:
                asyncio.create_task(conn.asr._send_stop_request())
            else:
                if len(conn.asr_audio) > 0:
                    asr_audio_task = conn.asr_audio.copy()
                    conn.reset_audio_states()

                    if len(asr_audio_task) > 0:
                        await conn.asr.handle_voice_stop(conn, asr_audio_task)
        elif msg_json["state"] == "detect":
            conn.client_have_voice = False
            conn.reset_audio_states()
            if "text" in msg_json:
                conn.last_activity_time = time.time() * 1000
                original_text = msg_json["text"]
                filtered_len, filtered_text = remove_punctuation_and_length(
                    original_text
                )

                is_wakeup_words = filtered_text in (conn.config.get("wakeup_words") or [])
                enable_greeting = conn.config.get("enable_greeting", True)

                if is_wakeup_words and not enable_greeting:
                    if conn.client_is_speaking and conn.client_listen_mode != "manual":
                        await handleAbortMessage(conn, from_wake_word=True)
                    await send_stt_message(conn, original_text)
                    await send_tts_message(conn, "stop", None)
                    conn.client_is_speaking = False
                elif is_wakeup_words:
                    conn.just_woken_up = True
                    enqueue_asr_report(conn, "嘿，你好呀", [])
                    await startToChat(conn, "嘿，你好呀", from_wake_word=True)
                else:
                    conn.just_woken_up = True
                    enqueue_asr_report(conn, original_text, [])
                    await startToChat(conn, original_text, from_wake_word=False)

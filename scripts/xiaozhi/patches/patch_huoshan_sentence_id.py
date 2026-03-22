#!/usr/bin/env python3
# 在容器内执行：python3 /tmp/patch_huoshan_sentence_id.py
# 为 huoshan_double_stream 的 FIRST/LAST 应用 message.sentence_id

from pathlib import Path

PATH = Path("/opt/xiaozhi-esp32-server/core/providers/tts/huoshan_double_stream.py")


def main() -> None:
    t = PATH.read_text(encoding="utf-8")
    marker = "finish_sid = getattr(message, \"sentence_id\", None)"
    if marker in t:
        print("Already patched, skip.")
        return

    old_first = """                if message.sentence_type == SentenceType.FIRST:
                    # 初始化参数
                    try:
                        if not getattr(self.conn, "sentence_id", None): 
                            self.conn.sentence_id = uuid.uuid4().hex
                            logger.bind(tag=TAG).debug(f"自动生成新的 会话ID: {self.conn.sentence_id}")"""

    new_first = """                if message.sentence_type == SentenceType.FIRST:
                    # 初始化参数
                    try:
                        if getattr(message, "sentence_id", None):
                            self.conn.sentence_id = message.sentence_id
                        elif not getattr(self.conn, "sentence_id", None): 
                            self.conn.sentence_id = uuid.uuid4().hex
                            logger.bind(tag=TAG).debug(f"自动生成新的 会话ID: {self.conn.sentence_id}")"""

    old_last = """                if message.sentence_type == SentenceType.LAST:
                    try:
                        logger.bind(tag=TAG).debug("开始结束TTS会话...")
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )"""

    new_last = """                if message.sentence_type == SentenceType.LAST:
                    try:
                        logger.bind(tag=TAG).debug("开始结束TTS会话...")
                        finish_sid = getattr(message, "sentence_id", None) or self.conn.sentence_id
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(finish_sid),
                            loop=self.conn.loop,
                        )"""

    if old_first not in t:
        raise SystemExit("FIRST block pattern not found — file changed?")
    if old_last not in t:
        raise SystemExit("LAST block pattern not found — file changed?")

    t = t.replace(old_first, new_first, 1).replace(old_last, new_last, 1)
    PATH.write_text(t, encoding="utf-8")
    print("huoshan_double_stream.py patched OK.")


if __name__ == "__main__":
    main()

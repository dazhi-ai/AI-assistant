"""Run inside xiaozhi container: set HuoshanDoubleStreamTTS resource_id to seed-tts-2.0."""
from __future__ import annotations

import re

PATH = "/opt/xiaozhi-esp32-server/data/.config.yaml"


def main() -> None:
    text = open(PATH, encoding="utf-8").read()
    if re.search(r"(?m)^\s*resource_id\s*:", text):
        text = re.sub(
            r"(?m)^(\s*)resource_id\s*:.*",
            r"\1resource_id: seed-tts-2.0",
            text,
        )
    else:
        nl = "\n"
        marker = "wss://openspeech.bytedance.com/api/v3/tts/bidirection" + nl
        insert = marker + "    resource_id: seed-tts-2.0" + nl
        if marker not in text:
            raise SystemExit("marker ws_url not found in .config.yaml")
        text = text.replace(marker, insert, 1)
    open(PATH, "w", encoding="utf-8").write(text)
    print("OK: resource_id -> seed-tts-2.0")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在宿主机或容器内：将「优先直接 play_music」规则写入 data/.xiaozhi_merged_prompt_body.txt。

用法：
  python3 patch_merged_prompt_play_music.py [/opt/xiaozhi-esp32-server/data]

若正文已含 [工具-播歌-务必遵守] 则跳过。依赖 UTF-8。
"""
from __future__ import annotations

import sys
from pathlib import Path

MARK = "[工具-播歌-务必遵守]"
OLD = (
    "- 要求播放歌曲→使用网易云音乐给客户搜索，下载。下载完成后，播放想要的音乐\n"
    "- 询问新闻"
)
NEW = (
    f"{MARK}\n"
    "- 用户明确说播歌、换歌、放音乐、点歌、来一首、换一首等时：**少口头铺垫**，"
    "不要先输出一大段寒暄或承诺再调工具；应**优先、尽快直接调用 play_music**，"
    "把 song_name / playlist_name / song_index 等参数一次填对；确有必要时再用**一句**极短口语衔接即可。\n"
    "- 实际播歌由网易云插件与设备播放链路完成；你**不要**用长篇文字描述"
    "「正在搜索、正在下载」来代替工具调用。\n\n"
    "- 询问新闻"
)


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/xiaozhi-esp32-server/data")
    path = root / ".xiaozhi_merged_prompt_body.txt"
    if not path.is_file():
        print(f"MISSING: {path}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print("SKIP: already patched")
        return
    if OLD not in text:
        print("ERR: expected old play-music bullet not found", file=sys.stderr)
        sys.exit(3)
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"OK: patched {path}")


if __name__ == "__main__":
    main()

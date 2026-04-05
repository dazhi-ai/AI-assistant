"""One-off ASR smoke test on server; run: python scripts/test_asr_volc.py

可选：ASR_TEST_CLUSTER=volcengine_streaming_common 覆盖 cluster 做对比测试。
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys
from pathlib import Path

# repo root on server: /opt/ai-assistant
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_settings

# 先加载 .env，再导入 ASRService（避免模块导入顺序导致未读环境变量）
load_settings()

from src.asr_service import ASRService


def make_silent_wav(sample_rate: int, duration_s: float = 0.4) -> bytes:
    n = int(sample_rate * duration_s)
    pcm = b"\x00\x00" * n
    data_size = len(pcm)
    hdr = bytearray(44)
    hdr[0:4] = b"RIFF"
    struct.pack_into("<I", hdr, 4, 36 + data_size)
    hdr[8:12] = b"WAVE"
    hdr[12:16] = b"fmt "
    struct.pack_into("<I", hdr, 16, 16)
    struct.pack_into("<H", hdr, 20, 1)
    struct.pack_into("<H", hdr, 22, 1)
    struct.pack_into("<I", hdr, 24, sample_rate)
    struct.pack_into("<I", hdr, 28, sample_rate * 2)
    struct.pack_into("<H", hdr, 32, 2)
    struct.pack_into("<H", hdr, 34, 16)
    hdr[36:40] = b"data"
    struct.pack_into("<I", hdr, 40, data_size)
    return bytes(hdr) + pcm


async def main() -> None:
    settings = load_settings()
    asr = ASRService(settings)
    test_cluster = os.getenv("ASR_TEST_CLUSTER", "").strip()
    if test_cluster:
        asr._volc_asr_cluster = test_cluster
        print("ASR_TEST_CLUSTER=", test_cluster)
    for sr in (16000, 44100, 48000):
        wav = make_silent_wav(sr)
        r = await asr.transcribe(wav)
        print(f"SR={sr} -> {r}")


if __name__ == "__main__":
    asyncio.run(main())

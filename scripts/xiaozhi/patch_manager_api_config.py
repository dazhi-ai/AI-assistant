#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在小智宿主机上执行：为 Python 端 data/.config.yaml 填写 manager-api，使其从智控台拉智能体（含 system_prompt）。

用法（secret 勿提交 Git，从小智库 sys_params 或智控台「参数管理」读取）：
  export XIAOZHI_MANAGER_SECRET='你的server.secret'
  python3 patch_manager_api_config.py

或：
  python3 patch_manager_api_config.py '<server.secret 值>'

manager-api.url 默认为 Docker 内网智控台：http://xiaozhi-esp32-server-web:8002/xiaozhi
若你的 compose 服务名不同，改脚本内 MANAGER_API_URL。
"""
from __future__ import annotations

import os
import pathlib
import sys

CONFIG_PATH = pathlib.Path("/opt/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml")
MANAGER_API_URL = os.environ.get(
    "XIAOZHI_MANAGER_API_URL",
    "http://xiaozhi-esp32-server-web:8002/xiaozhi",
)
OLD = (
    "manager-api:\n"
    "  url: \"\"\n"
    "  secret: \"\""
)


def main() -> None:
    secret = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("XIAOZHI_MANAGER_SECRET", "")).strip()
    if not secret:
        print("请传入 secret：环境变量 XIAOZHI_MANAGER_SECRET 或命令行第一个参数", file=sys.stderr)
        sys.exit(2)

    new_block = (
        "manager-api:\n"
        f"  url: {MANAGER_API_URL}\n"
        f"  secret: {secret}"
    )

    p = CONFIG_PATH
    if not p.is_file():
        print("missing", p, file=sys.stderr)
        sys.exit(2)
    t = p.read_text(encoding="utf-8")
    if OLD not in t:
        print("pattern not found; file may already be patched or format differs", file=sys.stderr)
        idx = t.find("manager-api")
        if idx >= 0:
            print(t[idx : idx + 160], file=sys.stderr)
        sys.exit(3)
    p.write_text(t.replace(OLD, new_block, 1), encoding="utf-8")
    print("patched", p)


if __name__ == "__main__":
    main()

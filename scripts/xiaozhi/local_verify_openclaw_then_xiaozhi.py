#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机执行：先 SSH → OpenClaw 上传 base_prompt 并 push.sh，再 SSH → 小智机直连查 MySQL。
不使用 OpenClaw 作为到小智的 SSH 跳板；MySQL 密码仅从 OpenClaw 的 push.env 读出用于小智 docker exec。

依赖：本机已配置好 ssh/scp 到两台机（与你在终端里能连上的方式一致）。

用法（在仓库根目录或任意目录）：
  python scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.py

可用环境变量覆盖默认主机（勿提交真实密码到 Git）：
  OPENCLAW_SSH=root@ip  OPENCLAW_PORT=22
  XIAOZHI_SSH=root@ip   XIAOZHI_PORT=1258
  LOCAL_BASE_PROMPT=d:\\...\\base_prompt.example-xiaozhi-with-news-placeholder.txt
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def _run(
    argv: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        input=input_bytes,
        capture_output=True,
        check=check,
    )


def _ssh_base(port: str, user_host: str) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=25",
        "-p",
        port,
        user_host,
    ]


def _load_push_env_from_openclaw(openclaw: str, port: str) -> tuple[str, str]:
    """从 OpenClaw 上 source push.env 后，用 base64 传出密码与 agent id（避免特殊字符断行）。"""
    # 不依赖 OpenClaw 上是否有 python3；base64 | tr 去掉换行
    remote = (
        "bash -lc "
        + shlex.quote(
            "source /opt/xiaozhi-push/push.env && "
            'printf %s "$MYSQL_PASSWORD" | base64 | tr -d "\\n" && echo && '
            'printf %s "$XIAOZHI_AGENT_ID" | base64 | tr -d "\\n" && echo'
        )
    )
    cp = _run([*_ssh_base(port, openclaw), remote], check=True)
    lines = cp.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if len(lines) < 2:
        raise RuntimeError("未能从 OpenClaw 解析 push.env（需 MYSQL_PASSWORD / XIAOZHI_AGENT_ID）")
    import base64

    pw = base64.b64decode(lines[0].encode()).decode("utf-8")
    aid = base64.b64decode(lines[1].encode()).decode("utf-8")
    if not pw or not aid:
        raise RuntimeError("MYSQL_PASSWORD 或 XIAOZHI_AGENT_ID 为空")
    return pw, aid


def _mysql_on_xiaozhi(
    xiaozhi: str,
    port: str,
    mysql_password: str,
    sql: str,
) -> str:
    """本机直连小智 SSH，docker exec mysql，SQL 走 stdin。"""
    docker_cmd = (
        "docker exec -i "
        f"-e MYSQL_PWD={shlex.quote(mysql_password)} "
        "xiaozhi-esp32-server-db mysql -uroot "
        "--default-character-set=utf8mb4 xiaozhi_esp32_server"
    )
    cp = _run(
        [*_ssh_base(port, xiaozhi), docker_cmd],
        input_bytes=(sql.strip() + "\n").encode("utf-8"),
        check=True,
    )
    return cp.stdout.decode("utf-8", errors="replace")


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    openclaw = os.environ.get("OPENCLAW_SSH", "root@43.134.240.219")
    openclaw_port = os.environ.get("OPENCLAW_PORT", "22")
    xiaozhi = os.environ.get("XIAOZHI_SSH", "root@124.223.174.173")
    xiaozhi_port = os.environ.get("XIAOZHI_PORT", "1258")
    local_base = Path(
        os.environ.get(
            "LOCAL_BASE_PROMPT",
            str(script_dir / "base_prompt.example-xiaozhi-with-news-placeholder.txt"),
        )
    )

    print("=== [1] scp base_prompt → OpenClaw ===")
    _run(
        [
            "scp",
            "-o",
            "ConnectTimeout=25",
            "-P",
            openclaw_port,
            str(local_base),
            f"{openclaw}:/opt/xiaozhi-push/base_prompt.txt",
        ],
        check=True,
    )

    print("=== [2] OpenClaw: push.sh ===")
    _run(
        [*_ssh_base(openclaw_port, openclaw), "bash /opt/xiaozhi-push/push.sh"],
        check=True,
    )
    print("PUSH_OK")

    print("=== [3] 从 OpenClaw push.env 读取 MYSQL_PASSWORD / XIAOZHI_AGENT_ID（不回显密码）===")
    mysql_pw, agent_id = _load_push_env_from_openclaw(openclaw, openclaw_port)
    print(f"XIAOZHI_AGENT_ID (from push.env): {agent_id}")

    # {新闻日报} utf-8 十六进制
    ph_hex = "7BE696B0E997BBE697A5E6A5A57D"
    sql_all = (
        "SELECT id, CHAR_LENGTH(system_prompt) AS prompt_chars, "
        f"LOCATE(CONVERT(UNHEX('{ph_hex}') USING utf8mb4), system_prompt) AS placeholder_pos "
        "FROM ai_agent;"
    )

    print("=== [4] 小智机（本机直连）: 各智能体长度与占位符 ===")
    out = _mysql_on_xiaozhi(xiaozhi, xiaozhi_port, mysql_pw, sql_all)
    print(out)

    aid_esc = agent_id.replace("'", "''")
    sql_row = (
        "SELECT SUBSTRING(system_prompt,1,220) AS prompt_head, "
        "SUBSTRING(system_prompt, GREATEST(1, CHAR_LENGTH(system_prompt)-340), 360) AS prompt_tail "
        f"FROM ai_agent WHERE id='{aid_esc}';"
    )

    print("=== [5] 小智机: push.env 目标智能体 正文头尾 ===")
    print(_mysql_on_xiaozhi(xiaozhi, xiaozhi_port, mysql_pw, sql_row))

    print("=== 完成 ===")
    print(
        "解读：placeholder_pos=0 表示已无 {新闻日报} 字面量；>0 表示合并未替换。"
        "若对话仍不对，请在小智机 docker restart xiaozhi-esp32-server 后让设备重连。"
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        stdout = (e.stdout or b"").decode("utf-8", errors="replace")
        print(stdout, file=sys.stdout)
        print(stderr, file=sys.stderr)
        sys.exit(e.returncode)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)

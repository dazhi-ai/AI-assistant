#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 SSH 在小智宿主机上执行 `docker exec mysql`，更新 ai_agent.system_prompt（完整正文）。

适用场景：
  - 轻量机与 MySQL 不在同一内网，或 MySQL 仅监听 Docker 网络、未对公网开放；
  - 不想用智控台 Bearer Token，改用「直连库」思路，但用 SSH 保证链路安全。

依赖：
  pip install paramiko  （仅本脚本需要）

环境变量（勿提交 Git）：
  SSH_HOST           小智服务器 IP 或域名
  SSH_PORT           SSH 端口，默认 22
  SSH_USER           SSH 用户名
  SSH_KEY_FILE       私钥路径（推荐）；与 SSH_PASSWORD 二选一
  SSH_PASSWORD       密码登录（次选）

  MYSQL_CONTAINER    MySQL 容器名，默认 xiaozhi-esp32-server-db
  MYSQL_USER         MySQL 用户，默认 root
  MYSQL_PASSWORD     MySQL 密码
  MYSQL_DATABASE     库名，默认 xiaozhi_esp32_server（与 docker-compose_all 一致）

  XIAOZHI_AGENT_ID   智能体 id（ai_agent.id）

  PROMPT_FILE        UTF-8 文件路径，内容为要写入的完整 system_prompt（整段覆盖）

可选：
  DRY_RUN=1          只打印将执行的 SQL 预览，不 SSH

说明：
  - 使用参数化 UPDATE（字符串经 MySQL 转义），避免日报正文里的引号/换行破坏 SQL。
  - 文档：docs/zhikongtai-cron-update-agent-prompt.md 第 4.1 节
"""

from __future__ import annotations

import os
import shlex
import sys


def _escape_mysql_literal(value: str) -> str:
    """转义为可安全放入单引号字符串字面量的形式（MySQL 标准）。"""
    return value.replace("\\", "\\\\").replace("'", "''").replace("\0", "")


def _build_sql(agent_id: str, prompt: str) -> str:
    esc_id = _escape_mysql_literal(agent_id)
    esc_prompt = _escape_mysql_literal(prompt)
    # 显式 SET NAMES，避免客户端/会话默认字符集非 utf8mb4 导致中文乱码。
    return (
        "SET NAMES utf8mb4;\n"
        f"UPDATE ai_agent SET system_prompt = '{esc_prompt}', updated_at = NOW() "
        f"WHERE id = '{esc_id}';\n"
    )


def main() -> None:
    try:
        import paramiko  # type: ignore
    except ImportError:
        print("请先安装: pip install paramiko", file=sys.stderr)
        sys.exit(2)

    host = os.environ.get("SSH_HOST", "").strip()
    port = int(os.environ.get("SSH_PORT", "22") or "22")
    user = os.environ.get("SSH_USER", "").strip()
    key_file = os.environ.get("SSH_KEY_FILE", "").strip()
    password = os.environ.get("SSH_PASSWORD", "")

    container = os.environ.get("MYSQL_CONTAINER", "xiaozhi-esp32-server-db").strip()
    m_user = os.environ.get("MYSQL_USER", "root").strip()
    m_pass = os.environ.get("MYSQL_PASSWORD", "")
    m_db = os.environ.get("MYSQL_DATABASE", "xiaozhi_esp32_server").strip()
    agent_id = os.environ.get("XIAOZHI_AGENT_ID", "").strip()
    prompt_path = os.environ.get("PROMPT_FILE", "").strip()
    dry = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    if not host or not user or not agent_id or not prompt_path:
        print(
            "请设置：SSH_HOST, SSH_USER, XIAOZHI_AGENT_ID, PROMPT_FILE；"
            "以及 SSH_KEY_FILE 或 SSH_PASSWORD、MYSQL_PASSWORD",
            file=sys.stderr,
        )
        sys.exit(2)

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()
    if not prompt.strip():
        print("PROMPT_FILE 为空", file=sys.stderr)
        sys.exit(2)

    sql = _build_sql(agent_id, prompt)

    # 用 MYSQL_PWD 传入密码，避免 -p 与特殊字符在远程 shell 中拆坏；容器内 mysql 客户端可读该环境变量。
    # shlex.join 逐参数转义，避免密码/库名中的引号、空格破坏命令。
    docker_inner = shlex.join(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            f"MYSQL_PWD={m_pass}",
            container,
            "mysql",
            "-u",
            m_user,
            "--default-character-set=utf8mb4",
            m_db,
        ]
    )
    # 远程用 bash -lc 执行一整条命令（含 docker 与各参数）。
    remote_cmd = f"bash -lc {shlex.quote(docker_inner)}"

    if dry:
        print("--- SQL ---")
        print(sql)
        print("--- remote ---")
        print(remote_cmd)
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kw: dict = {"hostname": host, "port": port, "username": user, "timeout": 30}
    if key_file:
        connect_kw["key_filename"] = key_file
    if password:
        connect_kw["password"] = password

    client.connect(**connect_kw)
    try:
        # 通过 stdin 把 SQL 送进 mysql，支持任意长度与 UTF-8 正文。
        stdin, stdout, stderr = client.exec_command(remote_cmd, get_pty=False)
        stdin.write(sql.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip(), file=sys.stderr)
        if exit_status != 0:
            sys.exit(exit_status)
    finally:
        client.close()


if __name__ == "__main__":
    main()

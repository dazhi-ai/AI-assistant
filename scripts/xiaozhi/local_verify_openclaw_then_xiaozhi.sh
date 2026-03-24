#!/usr/bin/env bash
# =============================================================================
# 在「本机」执行（需已配置好到两台机的 SSH 密钥）：
#   1) 本机 → OpenClaw：上传 base_prompt、执行 push.sh
#   2) 本机 → 小智：读 OpenClaw 上 push.env 中的 MYSQL_PASSWORD / XIAOZHI_AGENT_ID，
#      直连小智机 docker exec mysql 核对 ai_agent.system_prompt
#
# 用法：
#   export OPENCLAW_SSH='root@43.134.240.219'
#   export OPENCLAW_PORT='22'
#   export XIAOZHI_SSH='root@124.223.174.173'
#   export XIAOZHI_PORT='1258'
#   export LOCAL_BASE_PROMPT='/path/to/base_prompt.example-xiaozhi-with-news-placeholder.txt'
#   bash scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.sh
#
# Windows 可用 Git Bash 运行；勿将本脚本提交含密码的修改。
# =============================================================================
set -euo pipefail

OPENCLAW_SSH="${OPENCLAW_SSH:-root@43.134.240.219}"
OPENCLAW_PORT="${OPENCLAW_PORT:-22}"
XIAOZHI_SSH="${XIAOZHI_SSH:-root@124.223.174.173}"
XIAOZHI_PORT="${XIAOZHI_PORT:-1258}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BASE="${LOCAL_BASE_PROMPT:-$SCRIPT_DIR/base_prompt.example-xiaozhi-with-news-placeholder.txt}"

oc() { ssh -o BatchMode=yes -o ConnectTimeout=25 -p "$OPENCLAW_PORT" "$OPENCLAW_SSH" "$@"; }
xz() { ssh -o BatchMode=yes -o ConnectTimeout=25 -p "$XIAOZHI_PORT" "$XIAOZHI_SSH" "$@"; }

echo "=== [1] scp base_prompt → OpenClaw ==="
scp -o ConnectTimeout=25 -P "$OPENCLAW_PORT" "$LOCAL_BASE" "${OPENCLAW_SSH}:/opt/xiaozhi-push/base_prompt.txt"

echo "=== [2] OpenClaw: push.sh ==="
oc "bash /opt/xiaozhi-push/push.sh" && echo "PUSH_OK"

echo "=== [3] Read MYSQL_PASSWORD + XIAOZHI_AGENT_ID from OpenClaw push.env (values not printed) ==="
# shellcheck disable=SC2016
eval "$(oc 'source /opt/xiaozhi-push/push.env && printf "MYSQL_PASSWORD=%q\nXIAOZHI_AGENT_ID=%q\n" "$MYSQL_PASSWORD" "$XIAOZHI_AGENT_ID"')"

if [[ -z "${MYSQL_PASSWORD:-}" || -z "${XIAOZHI_AGENT_ID:-}" ]]; then
  echo "错误：未能从 push.env 解析 MYSQL_PASSWORD 或 XIAOZHI_AGENT_ID" >&2
  exit 2
fi

echo "XIAOZHI_AGENT_ID (from push.env): $XIAOZHI_AGENT_ID"

echo "=== [4] Xiaozhi (direct from local): all agents — length & placeholder ==="
# 占位符 {新闻日报} 的 utf8mb4 十六进制，避免脚本里直接嵌入中文进 SQL
PH_HEX='7BE696B0E997BBE697A5E6A5A57D'
SQL_ALL="SELECT id, CHAR_LENGTH(system_prompt) AS prompt_chars, LOCATE(CONVERT(UNHEX('${PH_HEX}') USING utf8mb4), system_prompt) AS placeholder_pos FROM ai_agent;"
# 远端 docker exec 从 stdin 读 SQL，MYSQL_PWD 用 %q 只转义密码，避免经 OpenClaw 跳板
MYSQL_DOCKER_CMD="$(printf 'docker exec -i -e MYSQL_PWD=%q xiaozhi-esp32-server-db mysql -uroot --default-character-set=utf8mb4 xiaozhi_esp32_server' "$MYSQL_PASSWORD")"
printf '%s\n' "$SQL_ALL" | xz "$MYSQL_DOCKER_CMD"

echo "=== [5] Xiaozhi: push.env 目标智能体 — 正文头尾（核对是否含「硬性规则」与简报）==="
# id 来自 push.env，假定为字母数字与连字符，避免 SQL 注入
AID_ESC="${XIAOZHI_AGENT_ID//\'/\'\'}"
SQL_ROW="SELECT SUBSTRING(system_prompt,1,220) AS prompt_head, SUBSTRING(system_prompt, GREATEST(1, CHAR_LENGTH(system_prompt)-320), 340) AS prompt_tail FROM ai_agent WHERE id='${AID_ESC}';"
printf '%s\n' "$SQL_ROW" | xz "$MYSQL_DOCKER_CMD"

echo "=== 完成 ==="
echo "解读：placeholder_pos=0 表示已替换；>0 表示库内仍有字面量占位符。若设备仍乱答，在小智机 docker restart xiaozhi-esp32-server 后重连设备再测。"

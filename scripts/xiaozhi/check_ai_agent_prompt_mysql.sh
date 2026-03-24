#!/usr/bin/env bash
# =============================================================================
# 在小智宿主机上执行：检查 MySQL 里各智能体的 system_prompt 是否异常。
#
# 用途：
#   - 若智控台「角色介绍」里有新闻，但设备回答对不上，先确认库里是否仍含未替换的
#     字面量「{新闻日报}」或错误智能体 id。
#
# 用法（在小智机 SSH 登录后）：
#   export MYSQL_PASSWORD='你的MySQL root 密码'
#   export MYSQL_CONTAINER='xiaozhi-esp32-server-db'   # 可选，默认值即此
#   bash check_ai_agent_prompt_mysql.sh
#
# 说明：
#   - base_prompt.txt 只存在于 OpenClaw 推送机，用于合并；小智机对话以本表为准。
#   - placeholder_pos > 0 表示合并未替换占位符，对话里不可能出现真实简报正文。
# =============================================================================
set -euo pipefail

CONTAINER="${MYSQL_CONTAINER:-xiaozhi-esp32-server-db}"
DB="${MYSQL_DATABASE:-xiaozhi_esp32_server}"
MUSER="${MYSQL_USER:-root}"

if [[ -z "${MYSQL_PASSWORD:-}" ]]; then
  echo "错误：请先 export MYSQL_PASSWORD='...'（与 docker-compose 中 MySQL root 一致）" >&2
  exit 2
fi

docker exec -e "MYSQL_PWD=${MYSQL_PASSWORD}" -i "${CONTAINER}" \
  mysql -u"${MUSER}" --default-character-set=utf8mb4 "${DB}" <<'SQL'
SELECT
  id,
  CHAR_LENGTH(system_prompt) AS prompt_chars,
  LOCATE('{新闻日报}', system_prompt) AS placeholder_pos,
  SUBSTRING(system_prompt, 1, 120) AS prompt_head,
  SUBSTRING(system_prompt, GREATEST(1, CHAR_LENGTH(system_prompt) - 199), 200) AS prompt_tail
FROM ai_agent;
SQL

# 本机执行：从 OpenClaw 读 push.env（base64），再直连小智查 ai_agent（不经 OpenClaw SSH 跳板）
# 用法：在 PowerShell 中
#   cd d:\AI-assistant\scripts\xiaozhi
#   .\run_xiaozhi_mysql_check_from_local.ps1

$ErrorActionPreference = "Stop"

$OpenClaw = "root@43.134.240.219"
$OpenClawPort = "22"
$Xiaozhi = "root@124.223.174.173"
$XiaozhiPort = "1258"

$cmd = 'source /opt/xiaozhi-push/push.env && printf %s "$MYSQL_PASSWORD" | base64 -w0 && echo && printf %s "$XIAOZHI_AGENT_ID" | base64 -w0 && echo'
$raw = & ssh -o BatchMode=yes -o ConnectTimeout=25 -p $OpenClawPort $OpenClaw "bash -lc '$cmd'"

$lines = ($raw -split "`n").ForEach({ $_.Trim() }) | Where-Object { $_ -ne "" }
if ($lines.Count -lt 2) { throw "未能从 OpenClaw 取得两行 base64" }

$pw = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($lines[0]))
$aid = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($lines[1]))

Write-Host "XIAOZHI_AGENT_ID (from push.env): $aid"

$phHex = "7BE696B0E997BBE697A5E6A5A57D"
$sqlAll = @"
SELECT id, CHAR_LENGTH(system_prompt) AS prompt_chars, LOCATE(CONVERT(UNHEX('$phHex') USING utf8mb4), system_prompt) AS placeholder_pos FROM ai_agent;
"@

$dockerMysql = "docker exec -i -e MYSQL_PWD=$pw xiaozhi-esp32-server-db mysql -uroot --default-character-set=utf8mb4 xiaozhi_esp32_server"

Write-Host "=== 小智机（本机直连）各智能体 ==="
$sqlAll | & ssh -o BatchMode=yes -p $XiaozhiPort $Xiaozhi $dockerMysql

$aidEsc = $aid.Replace("'", "''")
$sqlRow = @"
SELECT SUBSTRING(system_prompt,1,220) AS h, SUBSTRING(system_prompt, GREATEST(1, CHAR_LENGTH(system_prompt)-340), 360) AS t FROM ai_agent WHERE id='$aidEsc';
"@

Write-Host "=== 目标智能体 头尾 ==="
$sqlRow | & ssh -o BatchMode=yes -p $XiaozhiPort $Xiaozhi $dockerMysql

Write-Host "=== 完成（password 未打印）==="

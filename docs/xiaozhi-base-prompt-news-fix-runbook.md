# 运维手册：修正 base_prompt（新闻走系统提示词，非知识库）

> **两台机器**：`base_prompt.txt` / `push.sh` 在 **OpenClaw 宿主机**（如 `/opt/xiaozhi-push/`）；`push.env` 里的 **`SSH_HOST` / `SSH_PORT` 必须指向小智宿主机**（你方示例：**124.223.174.173:1258**），写库发生在小智机上的 MySQL 容器。详见 [`xiaozhi-server-deployment-notes.md`](xiaozhi-server-deployment-notes.md) §1.1。

## 1. 对照检查结论（修改前）

| 检查项 | 说明 |
|--------|------|
| **此前问题预测** | 若人设里写「询问新闻→在**自己的知识库**中找…」，而日报实际写在 **`system_prompt`**（未进 RAG），模型会按指令去检索知识库 → **表现为对话里找不到新闻**。 |
| **仓库内示例（已修正）** | [`scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt`](../scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt) 已**不含**「知识库找新闻」表述，并明确「只根据下方今日新闻简报」。 |
| **服务器上的文件** | 以 OpenClaw 宿主机常见路径 **`/opt/xiaozhi-push/base_prompt.txt`** 为准；**不在本 Git 仓库**，必须由你在 SSH 上 `cat`/`grep` 对照。 |

**在 OpenClaw 宿主机执行（只读检查）：**

```bash
# 是否仍含「去知识库找新闻」类表述（有输出则需改）
grep -nE '知识库|检索知识' /opt/xiaozhi-push/base_prompt.txt || echo "未匹配到知识库相关行（可继续确认全文）"

# 是否使用占位符合并（与 push.env 中 MERGE_MODE 必须一致）
grep -n '新闻日报' /opt/xiaozhi-push/base_prompt.txt || true
```

若 `base_prompt.txt` 里存在 **`{新闻日报}`**，则 **`/opt/xiaozhi-push/push.env` 中必须** 有：

```bash
MERGE_MODE=placeholder
```

若为 `append` 或 `markers` 却保留字面量 `{新闻日报}`，合并结果里会**原样出现** `{新闻日报}`，智控台会看到错误占位符。

---

## 1.5 小智机需要做什么？

- **不要**在小智机上找 `base_prompt.txt` 当「运行配置」；对话以 **MySQL `ai_agent.system_prompt`** 为准。  
- 排障时在 **小智机**运行：[`scripts/xiaozhi/check_ai_agent_prompt_mysql.sh`](../scripts/xiaozhi/check_ai_agent_prompt_mysql.sh)（见 [`xiaozhi-server-deployment-notes.md`](xiaozhi-server-deployment-notes.md) §6.5）。

## 2. 修改步骤（在 OpenClaw 宿主机 + 本机 scp）

### 2.1 备份服务器原文件

```bash
sudo cp -a /opt/xiaozhi-push/base_prompt.txt "/opt/xiaozhi-push/base_prompt.txt.bak.$(date +%Y%m%d%H%M)"
```

### 2.2 从本仓库上传修正后的 base（在 Windows 开发机执行）

将仓库中的示例文件覆盖为服务器上的 `base_prompt.txt`（路径按你本机调整）：

```powershell
# PowerShell：把 OPENCLAW_USER、OPENCLAW_HOST 换成你的 SSH 用户与 OpenClaw 机 IP
$env:OPENCLAW_USER = "root"
$env:OPENCLAW_HOST = "你的OpenClaw宿主机IP"
scp "d:\AI-assistant\scripts\xiaozhi\base_prompt.example-xiaozhi-with-news-placeholder.txt" `
  "${env:OPENCLAW_USER}@${env:OPENCLAW_HOST}:/opt/xiaozhi-push/base_prompt.txt"
```

或使用 Git Bash / WSL：

```bash
scp /d/AI-assistant/scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt \
  root@你的OpenClaw宿主机IP:/opt/xiaozhi-push/base_prompt.txt
```

### 2.3 确认 push.env 合并模式

```bash
grep MERGE_MODE /opt/xiaozhi-push/push.env
# 含 {新闻日报} 的 base 必须为：MERGE_MODE=placeholder
```

若不对，编辑 `push.env` 后保存（保持 **LF** 换行，可用 `tr -d '\r'` 去 CRLF）。

### 2.4 立即合并并写回小智库（与 cron 相同效果）

```bash
sudo bash /opt/xiaozhi-push/push.sh
```

### 2.5 小智侧重载（如对话仍像旧人设）

在小智**宿主机**：

```bash
docker restart xiaozhi-esp32-server
```

（容器名以 `docker ps` 为准。）

---

## 3. 验收

1. 智控台打开该智能体 → 角色介绍里应看到新表述（无「去知识库找当天新闻」）。  
2. 问「今天有什么新闻」→ 应能根据简报回答，不说「知识库里没有」。  

更全的排查见 [`xiaozhi-server-deployment-notes.md`](xiaozhi-server-deployment-notes.md) §6。

# OpenClaw（Docker）采集新闻 → SSH 更新小智智能体「今日新闻」

> **OpenClaw 任务说明书（定稿 prompt 的 Markdown 版）**：[`openclaw-xiaozhi-news-task-spec.md`](openclaw-xiaozhi-news-task-spec.md)

## 1. 你的目标架构（结构化理解）

| 组件 | 角色 |
|------|------|
| **远端轻量机** | Docker 内跑 **OpenClaw**（或同类自动化）：拉新闻 → 整理成**简报文本** |
| **链路** | 简报生成后，经 **SSH**（可配合密钥）连到 **小智 server**，更新数据库里智能体的配置 |
| **落点** | 智控台 / 小智共用的 MySQL 表 **`ai_agent.system_prompt`**（与界面「角色设定/系统提示」对应） |

注意：数据库里 **没有单独的「今日新闻」子字段**，只有 **一整段 `system_prompt`**。因此「只更新今日新闻」在实现上只能是下面两种之一：

1. **每次写入整段**：`固定人设与规则` + `今日新闻块`（**推荐**，最简单、最稳）。  
2. **模板 + 标记替换**：整段里用固定标记包住新闻区，脚本只替换标记之间的内容（人设不动，但仍需 **读旧值 → 替换 → 写回**，见下文脚本）。

---

## 2. 推荐数据流（与 OpenClaw 配合）

```
OpenClaw 容器/任务
  → 输出 daily_news.txt（仅今日简报，UTF-8）
宿主机编排（cron 或 OpenClaw 后置步骤）
  → merge：base_prompt.txt + daily_news.txt → full_prompt.txt
  → 调用本仓库脚本 SSH 到小智机更新库
```

- **`base_prompt.txt`**：长期稳定的人设、语气、禁忌（不放日报），放在轻量机**持久卷**里，版本可控。  
- **`daily_news.txt`**：OpenClaw **每天覆盖写入**（或任务结束写出）。  
- **`full_prompt.txt`**：合并结果，作为 `update_agent_prompt_mysql_via_ssh.py` 的 `PROMPT_FILE`。

合并可用本仓库脚本（无需手拼 shell）：

- `scripts/xiaozhi/merge_system_prompt_for_daily_news.py`  
  - 支持 **`append`**（人设后追加「今日新闻」一节）  
  - 支持 **`markers`**（在人设模板里预留 `<!-- DAILY_NEWS_START -->` … `<!-- DAILY_NEWS_END -->`，只替换中间）  
  - 支持 **`placeholder`**（把正文里的 **`{新闻日报}`** 换成 `daily_news.txt` 内容，与智控台原文一致时常用）

---

## 3. 推到小智 server 的两种方式（你已选 SSH）

### 3.1 SSH + `docker exec mysql`（与当前小智 Docker 部署一致）

使用：`scripts/xiaozhi/update_agent_prompt_mysql_via_ssh.py`  

环境变量：`SSH_HOST`、`SSH_PORT`、`SSH_USER`、`SSH_KEY_FILE`、`MYSQL_PASSWORD`、`XIAOZHI_AGENT_ID`、`PROMPT_FILE=full_prompt.txt` 等（见脚本头注释）。

OpenClaw 侧只要在**同一台轻量机**上能执行该脚本即可（脚本可装在宿主机，不必进 OpenClaw 镜像；若进镜像需带 `paramiko`）。

### 3.2 SSH 隧道 + 本机 `mysql` 客户端

见：`docs/zhikongtai-cron-update-agent-prompt.md` **§4.1 方式 A**。适合已在轻量机安装 `mysql` 客户端、且小智侧 MySQL 可转发到隧道的情况。

---

## 4. OpenClaw（Docker）侧落地建议

1. **密钥**：轻量机 → 小智机 **SSH 公钥**，禁止密码长期写在任务里。  
2. **编排**：用 **cron**（宿主机）或 **OpenClaw 定时工作流** 最后一步执行 shell：  
   `python3 merge_...py && python3 update_agent_prompt_mysql_via_ssh.py`  
3. **时区**：简报日期与「今日」一致，建议容器/宿主机设为 **`Asia/Shanghai`**。  
4. **失败告警**：SSH 或 MySQL 失败时 OpenClaw/邮件/Webhook 通知，避免静默断更。  
5. **生效**：更新库后若对话仍像旧稿，可 **设备重连** 或按需 **重启小智 Python 容器**（依你当前版本行为）。

---

## 5. 智控台里要配合的一件事

在智控台给该智能体配置的 **系统提示**，建议与 **`base_prompt.txt` 同源**：首次在网页里编辑好 → 导出/复制到轻量机 `base_prompt.txt`，之后**日常只通过脚本更新**，避免网页与文件两套人设不一致。

若使用 **标记模式**，请在智控台里也保留同样的 `<!-- DAILY_NEWS_START -->` / `END` 两段注释（或换用你自定义但固定的标记），与合并脚本配置一致。

---

## 6. 相关文件索引

| 文件 | 说明 |
|------|------|
| `docs/zhikongtai-cron-update-agent-prompt.md` | 智控台 API / MySQL / SSH 隧道细节 |
| `scripts/xiaozhi/update_agent_prompt_mysql_via_ssh.py` | SSH → `docker exec mysql` 写 `system_prompt` |
| `scripts/xiaozhi/update_agent_system_prompt_via_api.py` | 可选：HTTP `PUT`（需 Token） |
| `scripts/xiaozhi/merge_system_prompt_for_daily_news.py` | 人设 + OpenClaw 日报 → 整段 `system_prompt` |

---

## 7. 需求自检（逻辑）

- OpenClaw 只负责 **产出「今日简报」文本**；**不负责**猜小智库表结构——推送由固定脚本完成 → 职责清晰。  
- 库字段为 **整段文本** → 用 **合并后的全文** 更新，逻辑严谨。  
- SSH 密钥 + 最小权限 MySQL 用户（若单独建用户）→ 安全边界清楚。

若你后续提供 **OpenClaw 实际输出文件名/挂载路径**，可以把 §4 里的示例命令改成与你目录完全一致的一版「复制即用」`crontab` 行。

---

## 附录 A：当前是否已是「固定人设 + 日报」？如何从零做完连接与写入？

### A.1 当前情况说明（务必看清）

| 问题 | 结论 |
|------|------|
| 小智线上 `system_prompt` **是不是已经**变成「固定人设 + OpenClaw 日报」？ | **默认：没有。** 本仓库只提供**文档与脚本**，不会在无人执行的情况下改你服务器上的数据库。除非你**已在智控台手工改过**、或**已跑通下方脚本**并成功 `UPDATE`，否则仍是**智控台里最后一次保存**的那段文字。 |
| 怎样算「已经是这种形式」？ | 智控台打开该智能体 → **角色设定/系统提示**里能看到固定人设，且每天应由自动化刷新后面的「今日新闻」块（**append** 模式会在文末多一节；**markers** 模式在 `<!-- DAILY_NEWS_START -->` 与 `END` 之间变化）。 |

### A.2 你需要准备的信息（一次性收集）

在小智服务器上确认或记录：

1. **小智服务器公网 IP**（或 OpenClaw 能访问到的固定域名）。  
2. **SSH 端口**（你曾提过 **1258**，以实际 `sshd` 为准）。  
3. **SSH 登录用户**（如 `root` 或其它有 `docker` 权限的用户）。  
4. **MySQL 容器名**（全模块 Docker 常见为 **`xiaozhi-esp32-server-db`**）。  
5. **MySQL root 密码**（见 `docker-compose_all.yml` 里 `MYSQL_ROOT_PASSWORD`；**勿发到聊天/群**）。  
6. **数据库名**（常见为 **`xiaozhi_esp32_server`**）。  
7. **智能体 ID**：智控台 → 智能体 → 编辑，从 URL 或接口里复制 **`id`**（一长串，写入 `ai_agent.id`）。

### A.3 在 OpenClaw 所在机器（轻量服务器）上的操作

以下以 **脚本跑在 OpenClaw 的宿主机**为例（推荐：与 Docker 内 OpenClaw 通过**挂载目录**共享 `daily_news.txt`，宿主机跑 `python3` + `cron`）。

#### 步骤 1：安装依赖

```bash
# 示例：Debian/Ubuntu
sudo apt update && sudo apt install -y python3 python3-pip openssh-client
pip3 install --user paramiko
```

将本仓库中这两个文件拷到轻量机固定目录（例如 `/opt/xiaozhi-push/`）：

- `scripts/xiaozhi/merge_system_prompt_for_daily_news.py`  
- `scripts/xiaozhi/update_agent_prompt_mysql_via_ssh.py`

#### 步骤 2：准备「固定人设」与 OpenClaw 日报路径

1. 打开智控台 → 对应智能体 → 复制当前 **系统提示** 全文，保存为 **`base_prompt.txt`**（UTF-8）。  
   - 若用 **append** 模式：人设里**不要**重复写很长「今日新闻」，日报会由脚本追加在文末。  
   - 若用 **markers** 模式：在人设中**加入且仅加入一对**：  
     `<!-- DAILY_NEWS_START -->`（占位一行）`<!-- DAILY_NEWS_END -->`，并**先把这一版整段粘贴回智控台保存一次**，避免库里的旧内容没有标记导致合并失败。  

2. 配置 OpenClaw 任务：每天生成 **`daily_news.txt`**（UTF-8），写到宿主机路径，例如：  
   `/opt/xiaozhi-push/daily_news.txt`  
   （通过 Docker **volume** 挂载到 OpenClaw 容器内输出目录即可。）

#### 步骤 3：配置 SSH 免密登录（OpenClaw 机 → 小智机）

在 **OpenClaw 宿主机**执行：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_xiaozhi -N ""
ssh-copy-id -i ~/.ssh/id_ed25519_xiaozhi.pub -p <SSH端口> <用户>@<小智服务器IP>
```

测试：

```bash
ssh -p <SSH端口> -i ~/.ssh/id_ed25519_xiaozhi <用户>@<小智服务器IP> "docker ps --format '{{.Names}}' | head"
```

应能**无密码**列出容器。若小智机禁止 root 密码登录，只需保证 **公钥已写入** 对应用户的 `~/.ssh/authorized_keys`。

#### 步骤 4：确认小智机上可通过 `docker exec` 进 MySQL

在同一 SSH 会话中测试（密码仅本地输入，勿写进历史可改用 `.my.cnf`）：

```bash
ssh -p <端口> -i ~/.ssh/id_ed25519_xiaozhi <用户>@<小智IP> \
  "docker exec xiaozhi-esp32-server-db mysql -uroot -p'<MYSQL密码>' -e 'SELECT id, LEFT(system_prompt,80) FROM xiaozhi_esp32_server.ai_agent LIMIT 3;'"
```

能查出 `id` 与 `system_prompt` 前缀即表示链路正确。把你要更新的 **`id`** 记下来，填到环境变量 `XIAOZHI_AGENT_ID`。

#### 步骤 5：编写推送脚本与环境变量（推荐单独文件，权限 600）

在轻量机创建 `/opt/xiaozhi-push/push.env`（示例，请替换真值）：

```bash
export SSH_HOST='小智服务器IP'
export SSH_PORT='1258'
export SSH_USER='root'
export SSH_KEY_FILE="$HOME/.ssh/id_ed25519_xiaozhi"

export MYSQL_CONTAINER='xiaozhi-esp32-server-db'
export MYSQL_USER='root'
export MYSQL_PASSWORD='你的MySQL密码'
export MYSQL_DATABASE='xiaozhi_esp32_server'
export XIAOZHI_AGENT_ID='智控台里该智能体的id'

export BASE_PROMPT_FILE='/opt/xiaozhi-push/base_prompt.txt'
export DAILY_NEWS_FILE='/opt/xiaozhi-push/daily_news.txt'
export MERGE_MODE='append'
# 若用标记模式则: export MERGE_MODE='markers'
```

创建 `/opt/xiaozhi-push/push.sh`：

```bash
#!/bin/bash
set -euo pipefail
source /opt/xiaozhi-push/push.env
MERGED="/tmp/xiaozhi_full_prompt_$$.txt"
python3 /opt/xiaozhi-push/merge_system_prompt_for_daily_news.py > "$MERGED"
export PROMPT_FILE="$MERGED"
python3 /opt/xiaozhi-push/update_agent_prompt_mysql_via_ssh.py
rm -f "$MERGED"
```

```bash
chmod 700 /opt/xiaozhi-push/push.sh
chmod 600 /opt/xiaozhi-push/push.env
```

先手动执行一次：

```bash
bash /opt/xiaozhi-push/push.sh
```

然后到小智机或智控台确认 **`system_prompt` 已变**（智控台刷新页面看系统提示，或再跑步骤 4 的 `SELECT LEFT(system_prompt,...)`）。

#### 步骤 6：定时任务（每天简报生成之后）

若 OpenClaw 每天 **08:10** 写完 `daily_news.txt`，可 **08:15** 推一次：

```bash
crontab -e
# 每天 8:15（服务器本地时间，建议设为 Asia/Shanghai）
15 8 * * * /opt/xiaozhi-push/push.sh >> /var/log/xiaozhi-push.log 2>&1
```

确保 cron 使用的用户与 `SSH_KEY_FILE`、`push.env` 路径一致；若用系统 cron，密钥建议放在该用户家目录或显式 `export HOME=...`。

#### 步骤 7：生效与排错

| 现象 | 处理 |
|------|------|
| 智控台里已变，小智说话仍旧 | 设备 **重新联网/重连**；仍不行则 **重启** `xiaozhi-esp32-server` 容器（按你环境决定）。 |
| SSH 连不上 | 查小智机防火墙/安全组是否放行 **SSH 端口**；OpenClaw 机 `ssh -v` 看日志。 |
| `docker exec` 报权限 | SSH 用户需在小智机上有 **docker** 权限（如在 `docker` 组）。 |
| 合并报错 markers | 检查 `base_prompt.txt` 是否**恰好一对** START/END，且智控台已保存同结构。 |
| MySQL 密码含特殊字符 | 脚本已用 `MYSQL_PWD` 传入容器，一般可用；仍失败可检查密码中的引号。 |

### A.4 与「仅 OpenClaw 容器内跑命令」的说明

若必须在 **OpenClaw 容器内**执行推送：需在镜像内安装 `python3`、`paramiko`，并挂载：SSH 私钥、`push.env`、`base_prompt.txt`、脚本目录、以及 OpenClaw 写入的 `daily_news.txt`。运维复杂度高于 **宿主机 cron**，一般优先 **宿主机跑 push.sh**。

---

**文档版本说明**：以上步骤以常见 `xiaozhi-esp32-server` 全模块 Docker 部署为准；若你改过容器名、库名或 compose，请按实际替换环境变量。

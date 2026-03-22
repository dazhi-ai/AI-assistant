# 定时更新智控台「智能体系统提示词」（方案 3：每日新闻简报）

> **OpenClaw（Docker）远端采集 + SSH 推小智** 的端到端说明见：[openclaw-docker-news-to-xiaozhi.md](openclaw-docker-news-to-xiaozhi.md)

## 1. 目标

在**轻量服务器**上每天生成「新闻日报」文本后，自动写入智控台里某个智能体的 **`systemPrompt`（角色设定/系统提示）**，让小智对话时能参考当日要点。

## 2. 官方接口（manager-api）

智控台后端为 **Spring Boot**，上下文路径为 **`/xiaozhi`**（见上游 `application.yml`）。

| 说明 | 方法 | 路径 | 鉴权 |
|------|------|------|------|
| 更新智能体（**可只改提示词**） | `PUT` | `/xiaozhi/agent/{智能体ID}` | `Authorization: Bearer <token>` |

- **请求体 JSON** 只需包含要改的字段。上游 `AgentUpdateDTO` 为**部分更新**：例如只传 `systemPrompt` 时，其它模型/插件配置不会被动清空（`functions` 等未传则不改插件映射）。
- **字段名**：`systemPrompt`（与 Java 驼峰一致）。

**示例：**

```http
PUT http://你的智控台IP:8002/xiaozhi/agent/你的智能体UUID
Authorization: Bearer eyJhbGciOi...
Content-Type: application/json

{
  "systemPrompt": "你是小智助手。\n\n【今日新闻简报 2026-03-16】\n1. ...\n2. ..."
}
```

完整 OpenAPI 可在智控台所在环境浏览器打开：**`http://<IP>:8002/xiaozhi/doc.html`**（Knife4j），搜索「智能体管理 → 更新智能体」。

## 3. 如何拿到 `智能体ID` 与 `Bearer Token`

### 3.1 智能体 ID

1. 浏览器登录智控台 → **智能体** → 编辑目标智能体。  
2. 地址栏或接口里通常会出现 **一长串 ID**（UUID 无横杠或带横杠，以实际为准）。  
3. 或在已登录状态下请求：**`GET /xiaozhi/agent/list`**，从返回列表中取对应项的 `id`。

### 3.2 Token（难点说明）

登录接口为 **`POST /xiaozhi/user/login`**，上游实现里密码需 **SM2 加密**，并配合**图形验证码**，因此用 `curl` 一行登录**不现实**。

**可行做法（任选）：**

| 方式 | 适用场景 |
|------|----------|
| **A. 浏览器里复制 Token** | 登录智控台 → F12 → **Network**，点任意一条发往 `xiaozhi` 的请求，在 **Request Headers** 里找到 `Authorization: Bearer ...`，复制 token。把该 token 配到定时脚本环境变量（见下文）。Token 会过期，过期后需重新复制或再做自动登录。 |
| **B. Local Storage / Session** | F12 → **Application** → Local Storage，查找与 token 相关的键（不同前端版本键名可能为 `token`、`access_token` 等，以实际为准）。 |
| **C. 用脚本实现完整登录** | 需按前端同样逻辑：拉公钥 → SM2 加密密码 → 拉验证码 → 提交登录。维护成本高，仅建议在自动化要求高时再做。 |

**安全建议：** Token 等同登录态，勿提交到 Git；轻量机上用 `600` 权限文件或系统密钥仓库存放。

## 4. 数据库直写（免 Token，适合同内网/可连 MySQL）

若轻量机**无法访问**智控台 HTTP，但**能连**小智所用的 **MySQL**（建议仅内网 + 最小权限账号），可直接更新表：

- **表名**：`ai_agent`（上游实体 `AgentEntity`）
- **字段**：`system_prompt`（对应界面里的系统提示/角色设定）

示例（在 MySQL 客户端执行，**先备份**，并确认 `id` 正确）：

```sql
UPDATE ai_agent
SET system_prompt = '你是小智助手。\n\n【今日新闻简报】\n......',
    updated_at = NOW()
WHERE id = '你的智能体ID';
```

**注意：**

- 会**整段覆盖** `system_prompt`，请在生成日报的程序里拼好：**固定人设 + 当日简报**。
- 更新后，小智 Python 端是否**立即**拉取新配置取决于上游实现（常见为设备重连或下一轮拉配置）。若不生效，可尝试：**设备重连**或**重启 `xiaozhi-esp32-server` 容器**（按你环境决定）。

### 4.1 两台服务器之间用 SSH，再更新「完整正文」

**可以。** 思路有两种，都能写入**完整** `system_prompt`（含长文本、换行、中文），且不一定要把 MySQL 暴露到公网。

#### 方式 A：SSH 本地端口转发（轻量机上的客户端连 `127.0.0.1`）

在**轻量服务器**上建立隧道，把本地端口转到**小智服务器**上能访问到的 MySQL 地址：

```bash
# 示例：轻量机监听 13306，转发到小智机上的目标
# 若 MySQL 已映射到小智宿主机 127.0.0.1:3306（compose 里 ports: "3306:3306"）
ssh -N -p 22 \
  -L 127.0.0.1:13306:127.0.0.1:3306 \
  你的SSH用户@小智服务器IP
```

- **`-N`**：只做转发，不登录交互 shell（适合放后台或 systemd）。
- 若 `docker-compose_all.yml` 里 MySQL 只有 **`expose: 3306`**、没有 **`ports`**，则小智**宿主机**上可能没有 `127.0.0.1:3306`。此时转发目标应改为 **容器在 bridge 上的 IP**（在小智机上执行 `docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' xiaozhi-esp32-server-db` 查看），例如：

```bash
ssh -N -p 22 \
  -L 127.0.0.1:13306:172.19.0.2:3306 \
  用户@小智服务器IP
```

隧道建立后，在**轻量机**上用客户端执行 `UPDATE`（注意字符集 **utf8mb4**）：

```bash
mysql -h 127.0.0.1 -P 13306 -u root -p \
  --default-character-set=utf8mb4 \
  xiaozhi_esp32_server \
  -e "UPDATE ai_agent SET system_prompt = '...全文...', updated_at = NOW() WHERE id = '智能体ID';"
```

长正文建议写入 **`prompt.sql`**，再用 `mysql ... < prompt.sql`，避免 shell 对引号、长度不友好。

**安全建议：** SSH 用**密钥**登录；MySQL 账号尽量**专库专用户 + 最小权限**（仅 `UPDATE`/`SELECT` 于 `ai_agent`），不要用 root 长期跑定时任务（若可接受则至少限制来源 IP 为轻量机出口）。

#### 方式 B：不经由 MySQL 端口，SSH 上去 `docker exec mysql`（推荐与小智当前 compose 一致）

小智常见部署下 MySQL **未对宿主机映射端口**，方式 A 要记容器 IP。更省事的做法是：**轻量机只 SSH 到小智宿主机**，在远端执行：

```bash
docker exec -i xiaozhi-esp32-server-db mysql -uroot -p'密码' \
  --default-character-set=utf8mb4 xiaozhi_esp32_server \
  < prompt.sql
```

其中 `prompt.sql` 内含一条 `UPDATE ai_agent SET system_prompt = '...', updated_at = NOW() WHERE id = '...';`（注意 SQL 字符串内单引号需写成 `''`）。

本仓库提供 **Python + Paramiko** 脚本，自动完成「SSH → `docker exec -i` → stdin 写入 SQL」，并对正文做 **MySQL 转义**，避免手工拼 SQL 出错：

- **`scripts/xiaozhi/update_agent_prompt_mysql_via_ssh.py`**  
  依赖：`pip install paramiko`  
  环境变量见脚本头部注释（`SSH_HOST`、`SSH_KEY_FILE`、`PROMPT_FILE`、`XIAOZHI_AGENT_ID`、`MYSQL_PASSWORD` 等）。

---

## 5. 推荐部署形态（经济可行）

1. **轻量机**：cron 每天生成 `daily_digest.txt`（或一段 JSON）。  
2. **推送**：  
   - **优先**：轻量机能访问 `http://小智服务器:8002` 时，用本仓库脚本 **`scripts/xiaozhi/update_agent_system_prompt_via_api.py`**（只发 `systemPrompt`）。  
   - **否则**：把文件 `scp` 到小智服务器，在小智机上执行同一脚本；或用 **MySQL 直写**（第四节）。

## 6. 提示词拼接建议

- **固定前缀**（人设、语气、禁止编造等）放在程序里常量中。  
- **每日块**用明确标题包起来，例如：`【今日新闻简报 日期】`，并注明「仅作参考，以权威媒体为准」。  
- 控制总长度：过长可能被模型截断或影响费用，建议简报 **800～2000 字**级先试。

---

## 7. 与本项目脚本的关系

| 脚本 | 作用 |
|------|------|
| `scripts/xiaozhi/update_agent_system_prompt_via_api.py` | `PUT /xiaozhi/agent/{id}`，需 Bearer Token |
| `scripts/xiaozhi/update_agent_prompt_mysql_via_ssh.py` | SSH 到小智机 → `docker exec mysql`，免 Token、适合 MySQL 未映射公网 |

上游仓库：`https://github.com/xinnan-tech/xiaozhi-esp32-server`（`manager-api`）。

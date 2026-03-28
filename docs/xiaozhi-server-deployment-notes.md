# 小智 / OpenClaw 相关部署重点注意事项

> **维护前请先阅读本文**，避免从本仓库拉代码或改配置后，与线上服务器行为不一致（尤其是安全改造后的环境变量、未入库文件、定时任务）。

---

## 1. 文档定位

| 文档 | 用途 |
|------|------|
| **本文** | 运维「易踩坑」清单：仓库 vs 服务器差异、密钥、定时、编码 |
| [`openclaw-docker-news-to-xiaozhi.md`](openclaw-docker-news-to-xiaozhi.md) | OpenClaw → 小智 新闻推送架构 |
| [`openclaw-xiaozhi-news-task-spec.md`](openclaw-xiaozhi-news-task-spec.md) | OpenClaw 任务说明书（定稿） |
| [`zhikongtai-cron-update-agent-prompt.md`](zhikongtai-cron-update-agent-prompt.md) | 智控台 API / SSH 写库细节 |

### 1.1 两台服务器别混（OpenClaw 轻量机 vs 小智宿主机）

| 角色 | 典型用途 | 说明 |
|------|----------|------|
| **OpenClaw 宿主机** | 跑 OpenClaw、cron 调 `push.sh`；存放 `base_prompt.txt`、`daily_news.txt`、`merge_*.py`、`push.env` | 你本机 SSH **改推送脚本/人设模板** 时，连的是这台（例如历史上用过的轻量机公网 IP）。 |
| **小智宿主机** | `xiaozhi-esp32-server`、MySQL、Docker；智控台读写的库在这边的库/容器里 | **`push.env` 里的 `SSH_HOST` / `SSH_PORT` 必须指向这台**，`update_agent_prompt_mysql_via_ssh.py` 会 SSH 进来再 `docker exec mysql` 写 `ai_agent.system_prompt`。 |

**易错点**：用 SSH 登录 **OpenClaw 机**改完 `base_prompt.txt` 并不等于「连错了小智」——合并与写库是 **OpenClaw 上执行脚本 → 再 SSH 到小智机** 完成的。若 `SSH_HOST` 误填成 OpenClaw 自己的 IP，才会出现「智控台像没更新 / 对话与简报无关」等异常。

**你当前环境（示例，以 `push.env` 为准）**：小智宿主机 **`124.223.174.173`，SSH 端口 `1258`，用户 `root`**（与智控台文档里常见示例一致）。OpenClaw 轻量机与该机 **不是同一台**。

### 1.2 小智服务器要不要改 `base_prompt.txt`？

**一般不需要、也通常找不到这份文件。**  
- **`base_prompt.txt`**：放在 **OpenClaw 推送机**（如 `/opt/xiaozhi-push/`），用来和 `daily_news.txt` **合并**，再经 SSH 写入小智 MySQL。  
- **设备对话实际读的是**：小智库表 **`ai_agent.system_prompt`**（智控台「角色介绍」展示的同源数据）。  

因此：**让新闻「指向角色介绍」的文案修改，应在 OpenClaw 的 `base_prompt.txt` 完成并重新 `push.sh`**；到小智机上应做的是 **查库验证 + 重启 `xiaozhi-esp32-server` 容器**，而不是去找 `base_prompt.txt` 改一份「本地副本」（除非你在小智机另做备份，那份不参与运行）。

### 1.3 本机两路 SSH：改 OpenClaw、查小智（不要经 OpenClaw 再 SSH 到小智）

运维时建议固定为：

| 步骤 | 从哪连 | 做什么 |
|------|--------|--------|
| 改人设 / 跑推送 | **本机 → OpenClaw**（`scp`、`ssh` 执行 `push.sh`） | 更新 `/opt/xiaozhi-push/base_prompt.txt` 并写小智 MySQL |
| 核对库里是否真是合并后的正文 | **本机 → 小智宿主机**（`ssh -p 1258` 等） | `docker exec … mysql` 查 `ai_agent`，**不要**先登录 OpenClaw 再 `ssh` 到小智（除非你没有小智直连密钥、只能用跳板） |

本仓库提供 **本机一键核对**（从 OpenClaw 只读取出 `MYSQL_PASSWORD` / `XIAOZHI_AGENT_ID` 的 base64，不在聊天里手抄密码）：

- **Windows PowerShell**：[`scripts/xiaozhi/run_xiaozhi_mysql_check_from_local.ps1`](../scripts/xiaozhi/run_xiaozhi_mysql_check_from_local.ps1)  
- **有 Python 时**：[`scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.py`](../scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.py)（含 scp + `push.sh` + 直连查库）  
- **有 Bash 时**：[`scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.sh`](../scripts/xiaozhi/local_verify_openclaw_then_xiaozhi.sh)  

**如何读查询结果**：`placeholder_pos = 0` 表示库内**没有**字面量 `{新闻日报}`，合并已生效；`> 0` 表示占位符仍在库里。若此项为 0 但设备仍乱答，按 §6.2 / §6.3 **重启小智容器并核对设备绑定的智能体 `id` 与 `push.env` 一致**。

---

## 2. 不在 Git 中的文件（服务器上必须单独维护）

以下文件**不会**随 `git pull` 出现，克隆新仓后需**手工创建或从备份恢复**：

| 路径（常见） | 内容 | 风险 |
|--------------|------|------|
| **`.env`**（本仓库根目录） | `AI-assistant` 本地助手、`python main.py` 用 | 勿提交；与**小智 Docker**无直接关系 |
| **`scripts/xiaozhi/push.env`** | OpenClaw 宿主机：`SSH_*`、`MYSQL_*`、`XIAOZHI_AGENT_ID`、`MERGE_MODE` 等 | 丢失则 `push.sh` 无法 SSH 写库 |
| **`/opt/xiaozhi-push/push.env`**（线上） | 同上，实际运行路径 | 同左 |
| **`.cursor/`** | 编辑器本地状态 | 已 `.gitignore`，勿提交 |

另：下列脚本因曾含**网易云 Cookie** 等敏感信息，**刻意不入库**（见 `.gitignore`）。若你需要同类功能，请在本机保留副本或用环境变量版工具替代：

- `scripts/xiaozhi/get_user_id.py`
- `scripts/xiaozhi/test_netease_connection.py`
- `scripts/xiaozhi/write_netease_config.py`
- `scripts/xiaozhi/fix_netease_config.py`
- `scripts/xiaozhi/xiaozhi-config-local-tts.yaml`

**操作前检查**：`ls -la /opt/xiaozhi-push/push.env` 是否存在、`chmod 600` 是否仍有效。

---

## 3. 网易云 `play_music` 插件（安全改造后与旧部署的差异）

本仓库中的 `scripts/xiaozhi/plugins_func/functions/play_music_netease.py` 已**移除硬编码 Cookie/UserId**。

### 3.1 配置优先级（合并后生效）

1. **小智容器内** `data/.config.yaml`（或智控台生成的配置）里 `plugins.play_music` 的 `netease_cookie`、`netease_user_id`、`netease_api_url`  
2. 若未配置，则使用**进程环境变量**（见下）  
3. 再否则使用代码内默认（仅 `NETEASE_API_URL` 默认 `http://172.17.0.1:3000`，Cookie/UserId **默认为空**）

### 3.2 环境变量（Docker / systemd 中配置）

| 变量 | 说明 |
|------|------|
| `NETEASE_COOKIE` | 网易云登录 Cookie 字符串（与旧版硬编码等效） |
| `NETEASE_USER_ID` | 网易云用户数字 ID |
| `NETEASE_API_URL` | 自建网易云 API 根地址，默认 `http://172.17.0.1:3000` |

**若从 Git 更新插件文件后「放不了歌」**：优先检查 Cookie/UserId 是否仍只写在旧版「硬编码」里而未迁到 **yaml 或环境变量**。

### 3.3 部署插件到线上小智容器

仍按文件头注释流程：`scp` → `docker cp` → 删容器内 `__pycache__` → `docker restart xiaozhi-esp32-server`。  
若与 `abortHandle` 等补丁配合，见 `scripts/xiaozhi/patches/README-netease-playback.md`。

### 3.4 和风天气 `get_weather` 插件（分钟级降水）

若你希望用户直接问 **「几点几分下雨」**、**「雨什么时候停」**、**「未来一小时会不会下雨」**、**「要不要带伞」**，则线上小智需使用**带分钟级降水逻辑**的 `get_weather.py`。

#### 当前线上配置落点

- **配置文件**：`/opt/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`
- **插件配置键**：`plugins.get_weather.api_key`、`plugins.get_weather.api_host`、`plugins.get_weather.default_location`
- **插件源码（宿主机）**：`/opt/xiaozhi-esp32-server/main/xiaozhi-server/plugins_func/functions/get_weather.py`
- **插件生效路径（容器内）**：`/opt/xiaozhi-esp32-server/plugins_func/functions/get_weather.py`

#### 判定是否为新版分钟级插件

新版插件通常应包含这些标记：

- `fetch_minutely_weather`
- `time_query`
- 分钟级接口路径 `/v7/minutely/5m`
- 对「雨什么时候停 / 几分下雨 / 带伞」等问法的判断逻辑

若线上文件里**没有**这些标记，说明仍是旧版，仅能回答基础天气或粗粒度降雨判断。

#### 线上部署步骤（推荐）

1. 将仓库中的 `scripts/xiaozhi/patches/get_weather.py` 上传到服务器临时目录，例如 `/tmp/get_weather.py`
2. 先备份宿主机旧文件，再覆盖宿主机源码路径
3. 再执行 `docker cp` 覆盖容器内生效路径
4. 删除宿主机与容器内相关 `__pycache__`
5. 重启 `xiaozhi-esp32-server`

#### 快速验证

可在服务器上直接用当前 `data/.config.yaml` 中的 `api_key/api_host` 发起和风天气请求，至少核对：

- `GeoAPI` 返回 `code=200`
- `weather/24h` 返回 `code=200`
- `minutely/5m` 返回 `code=200`
- `minutely` 数组非空

若以上都正常，但设备仍答不出「几点几分下雨 / 雨什么时候停」，优先检查：

1. 运行中的容器是否已重启并加载到新插件
2. 设备当前绑定的智能体是否确实走这台小智服务
3. 是否存在上游缓存或设备未重连

---

## 4. OpenClaw 宿主机：`daily_news.txt` 与 `push.sh`

### 4.1 角色分工

- **OpenClaw**：按任务说明在 **:45** 左右生成并覆盖 **`/opt/xiaozhi-push/daily_news.txt`**（UTF-8、无 BOM）。  
- **cron（root）**：在 **09:00、12:00、17:00、22:00**（北京时间，服务器 `Asia/Shanghai`）执行 `push.sh`，合并 `base_prompt.txt` 并 SSH 写小智 MySQL。

### 4.2 易错点

| 问题 | 处理 |
|------|------|
| **`push.env` CRLF** | Windows 编辑后易出现 `Bad port '1258\r'`；在服务器执行 `tr -d '\r' < push.env > /tmp/f && mv /tmp/f push.env` |
| **`SSH_KEY_FILE` 路径错误** | 须指向**真实私钥**（如 `~/.ssh/id_ed25519`），与 `ssh-copy-id` 到小智机的一致 |
| **智控台乱码** | `daily_news.txt` / 合并结果须 UTF-8；写库脚本已含 `SET NAMES utf8mb4`（见 `update_agent_prompt_mysql_via_ssh.py`） |
| **OpenClaw 与 cron 双跑 `push.sh`** | 若 prompt 要求 OpenClaw 写文件后再执行 `push.sh`，可能与 cron **重复写库**；一般可接受，若要单一路径需关其一 |

### 4.3 修改小智 MySQL root 密码后

须同步：`docker-compose_all.yml` 中 `MYSQL_ROOT_PASSWORD`、`SPRING_DATASOURCE_DRUID_PASSWORD`，重建 **db + web** 容器，并更新 **`push.env` 的 `MYSQL_PASSWORD`**。

---

## 5. 小智服务器（Docker 全模块）

- **compose 路径（常见）**：`/opt/xiaozhi-esp32-server/main/xiaozhi-server/docker-compose_all.yml`  
- **MySQL 容器名（常见）**：`xiaozhi-esp32-server-db`  
- **库名（常见）**：`xiaozhi_esp32_server`；智能体表 **`ai_agent.system_prompt`** 与智控台「角色介绍」对应  
- **SSH 写库**：OpenClaw 机用户需对小智机 **`docker exec`** 无密码或密钥登录，且具备 **docker** 权限

---

## 6. 故障排查：智控台「角色介绍」里已有新闻，对话却说找不到 / 要去知识库找

常见原因按优先级处理：

### 6.1 人设文案与落点不一致（最常见）

若 `system_prompt` 里写了类似 **「询问新闻→在自己的知识库中找」**，而日报实际是 **写进系统提示词**（未进 RAGFlow / 智控台知识库文档），模型会按指令去走「知识库检索」，结果为空，表现为「找不到新闻」。

**处理**：把交互指南改成明确要求 **根据本提示词内「今日新闻简报」正文** 回答（见仓库示例 [`scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt`](../scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt)）。改完后需 **重新合并 base + daily_news 并写库**（或等下次 `push.sh`），并确认智控台保存的是新版本。  
**逐步命令（备份、scp、MERGE_MODE、push.sh）**：[`xiaozhi-base-prompt-news-fix-runbook.md`](xiaozhi-base-prompt-news-fix-runbook.md)。

### 6.2 服务端仍用旧缓存

部分部署下 **`xiaozhi-esp32-server` 会在连接建立或启动时加载智能体配置**，仅改 MySQL 后未重载，对话仍用旧 `system_prompt`。

**处理**：在小智宿主机执行 **`docker restart xiaozhi-esp32-server`**（容器名以实际为准），并让设备 **重连 WebSocket** 后再测。

### 6.3 设备绑定的不是被更新的智能体

智控台里 **A 智能体** 已更新，但设备 MQTT/配置绑定的是 **B 智能体**。

**处理**：核对设备所用 **智能体 ID** 与 `push.env` / 写库脚本里的 **`XIAOZHI_AGENT_ID`**、智控台编辑页是否为同一条记录。

### 6.3.1 智控台页面上查不到智能体 ID

部分版本 **不在表格里展示 `id`**。请按 **[`zhikongtai-cron-update-agent-prompt.md`](zhikongtai-cron-update-agent-prompt.md) §3.1.1** 用 **F12 → Network 看 `agent/list` 响应**、**Knife4j**、或 **小智机 MySQL 查 `ai_agent.id`**；已配置推送时还可看 OpenClaw **`push.env` 的 `XIAOZHI_AGENT_ID`**。

### 6.4 若你确实使用 RAG 知识库

只有当日报 **导入 RAGFlow 并绑定到该智能体** 时，「去知识库找新闻」类指令才成立；否则应走 **6.1** 的表述。参见 [`xiaozhi-knowledge-vs-local-ingest.md`](xiaozhi-knowledge-vs-local-ingest.md)。

### 6.5 智控台里简报看起来对，但小智回答与简报「完全对不上」

先排除 **库里根本不是合并后的正文**（常见于占位符未替换、更新了别的智能体）：

1. **在小智宿主机**执行检查脚本（需 MySQL 密码，**勿**把密码写进仓库）：  
   [`scripts/xiaozhi/check_ai_agent_prompt_mysql.sh`](../scripts/xiaozhi/check_ai_agent_prompt_mysql.sh)  
   - 看输出里每一行的 **`placeholder_pos`**：若 **大于 0**，说明该智能体 `system_prompt` 里仍残留字面量 **`{新闻日报}`**，合并/写库有问题，设备永远读不到真实简报。  
   - 核对 **`id`** 是否与 **`push.env` 的 `XIAOZHI_AGENT_ID`**、设备绑定的智能体 **完全一致**。  

2. **已确认库里有真实简报正文** 仍乱答：  
   - 执行 **`docker restart xiaozhi-esp32-server`**（容器名以 `docker ps` 为准），设备 **断连再连** 后重测。  
   - 在 OpenClaw 更新人设：在 **`{新闻日报}` 合并后的内容之后** 增加「硬性规则」段落，明确要求 **必须先据简报作答、禁止推脱**（见仓库示例文件末尾 [`base_prompt.example-xiaozhi-with-news-placeholder.txt`](../scripts/xiaozhi/base_prompt.example-xiaozhi-with-news-placeholder.txt)），再 **`push.sh`** 写库。

### 6.6 日志里出现「使用快速提示词」——对话不会用智控台「角色介绍」

**现象（`docker logs xiaozhi-esp32-server`）**：  
`core.utils.prompt_manager`-INFO-**使用快速提示词** …（例如默认台湾腔人设），随后「构建增强提示词成功，长度: 约 2000」。  
这说明 Python 端 **没有从 manager-api / 数据库拉取该智能体的完整 `system_prompt`**，而是在用内置快捷人设；因此 **无论 MySQL 里 `ai_agent.system_prompt` 写得多对，语音对话都对不上**。

**常见原因**：

1. **`data/.config.yaml` 里 `manager-api.url` / `manager-api.secret` 为空**（或未配置）。  
2. **把 `manager-api` 填上了，但同一文件里仍保留 `selected_module`、`LLM:`、`ASR:`、`TTS:` 等本地模块块** —— 上游会报 **「既包含智控台配置又包含本地配置」** 并可能反复崩溃；正确做法是二选一：  
   - **走智控台**：使用与官方 **`config_from_api.yaml`** 同类的 **最小配置**（仅 `server` + `manager-api` + `prompt_template`），模块与提示词全部由智控台下发。仓库示例：[`scripts/xiaozhi/dot_config_from_api.template.yaml`](../scripts/xiaozhi/dot_config_from_api.template.yaml)（将 `MANAGER_SECRET_PLACEHOLDER` 换成 **`sys_params` 中 `server.secret`**，与 [`任务1.3-智控台部署与接入指南.md`](../任务1.3-智控台部署与接入指南.md) §6 一致）。  
   - **纯本地**：`manager-api` 留空，只用本地 yaml（此时智控台「角色介绍」**不会**进语音链路）。

**`server.secret` 查询（小智 MySQL）**：`sys_params` 表 `param_code = 'server.secret'` 的 `param_value`。

**回退到纯本地配置（你已验证智控台全下发时 TTS 不响）**：将 `data/.config.yaml` 恢复为 **`manager-api.url` / `secret` 均为空字符串**，且保留完整的 `selected_module`、`LLM`、`ASR`、`TTS` 等块（与官方「仅 config_from_api」互斥，不可混填）。服务器上若曾备份 **`data/.config.yaml.bak.managerapi`**，即为一种可用的本地版快照；恢复后执行 **`docker restart xiaozhi-esp32-server`**。  
**代价（未做文件同步时）**：语音链路会回到 **「快速提示词」**，**不会**用 MySQL 里长 `system_prompt`。

**本地模式 + 日报（与 `push.sh` 联用，须理解上游机制）**：`manager-api.url` 为空时，**语音链路不会**每连接去拉 MySQL；`core/utils/prompt_manager.py` 用 **`data/.config.yaml` 里的 `prompt` 字段**作为 `base_prompt`，再拿 **`prompt_template` 指向的文件**做 Jinja 渲染。官方 [`agent-base-prompt.txt`](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/agent-base-prompt.txt) **第一行就是 `{{ base_prompt }}`**，后面是语言/emoji/天气等壳子。若把「人设+简报全文」只 `scp` 进 `agent-base-prompt.txt` 却**没有**在 yaml 里写 **`prompt:`**，则 `config["prompt"]` 仍是根目录 `config.yaml` 里自带的**默认「小智/小志」短文**（日志里「使用快速提示词」+ 长度约 **1997**），**与智控台「角色介绍」必然不一致**。

**推荐做法**：OpenClaw [`push.sh.openclaw`](../scripts/xiaozhi/push.sh.openclaw) 已改为：① 将合并正文放到挂载目录下的 **`.xiaozhi_merged_prompt_body.txt`**；② 将仅含 **`{{ base_prompt }}`** 的 [`agent-base-prompt.jinja.txt`](../scripts/xiaozhi/agent-base-prompt.jinja.txt) 覆盖为 **`agent-base-prompt.txt`**；③ 在容器内执行 [`inject_local_prompt_config.py`](../scripts/xiaozhi/inject_local_prompt_config.py)，把正文写入 **`data/.config.yaml` 的 `prompt` 键**；④ **`docker restart`**。OpenClaw 上需一并部署 **`/opt/xiaozhi-push/agent-base-prompt.jinja.txt`** 与 **`inject_local_prompt_config.py`**。关闭同步：`SYNC_LOCAL_PROMPT=0`。

---

## 7. 本仓库 `AI-assistant` 本地服务（与小智链路区分）

| 配置 | 用途 |
|------|------|
| `KNOWLEDGE_HTTP_PORT` / `KNOWLEDGE_INGEST_TOKEN` | 仅 **`python main.py` WebSocket 助手** 的知识注入 HTTP，**不**自动进小智硬件对话 |
| 详见 [`xiaozhi-knowledge-vs-local-ingest.md`](xiaozhi-knowledge-vs-local-ingest.md) | 避免误以为本地 ingest 等于智控台知识库 |

---

## 8. 发布检查清单（建议每次上大变更前打勾）

- [ ] 未将 `.env`、`push.env`、Cookie、私钥提交 Git  
- [ ] 线上 `push.env` 与当前 MySQL 密码、智能体 `id`、SSH 密钥路径一致  
- [ ] `daily_news.txt` / `base_prompt.txt` 为 UTF-8，无 BOM；`push.env`/`push.sh` 为 LF  
- [ ] 更新 `play_music` 插件后，已配置 **yaml 或环境变量** 中的网易云 Cookie/UserId  
- [ ] `crontab -l` 确认 `push.sh` 仍存在且时区为北京时间预期  
- [ ] 智控台能登录，且角色介绍中文无乱码（抽检）

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-03-23 | 初版：固化 push/OpenClaw、play_music 环境变量、不入库文件、MySQL/编码注意事项 |
| 2026-03-24 | 增加 §6：智控台有新闻但对话找不到（人设与知识库表述、缓存、智能体 ID） |
| 2026-03-24 | 增加 §1.1：OpenClaw 机 vs 小智机（`SSH_HOST` 须指向小智；示例 124.223.174.173:1258） |
| 2026-03-24 | 增加 §1.2（小智机不必改 base_prompt）、§6.5（库内占位符/智能体 id 排查）、检查脚本 `check_ai_agent_prompt_mysql.sh` |
| 2026-03-24 | 增加 §1.3：本机两路 SSH；`run_xiaozhi_mysql_check_from_local.ps1` / `local_verify_openclaw_then_xiaozhi.py|.sh` |
| 2026-03-24 | §6.3.1 智控台查不到智能体 id；`zhikongtai-cron` §3.1.1；`list_ai_agent_ids.example.sql` |
| 2026-03-24 | §6.6：日志「快速提示词」与 manager-api 纯配置；`dot_config_from_api.template.yaml` |
| 2026-03-24 | §6.6 末：智控台全下发 TTS 异常时回退本地 `bak.managerapi` 与代价说明 |
| 2026-03-24 | 本地模式+日报：`push.sh` 注入 `prompt` + Jinja 壳 `{{ base_prompt }}` + `.xiaozhi_merged_prompt_body.txt`；§6.6 机制说明 |

---

*维护完成后若引入新密钥或新路径，请同步更新本文对应小节。*

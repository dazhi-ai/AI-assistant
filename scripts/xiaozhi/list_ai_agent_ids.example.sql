-- 在小智 MySQL 中列出智能体 id，供「智控台不显示 id」时对照。
-- 在宿主机执行示例：
--   docker exec -i -e MYSQL_PWD='你的密码' xiaozhi-esp32-server-db mysql -uroot --default-character-set=utf8mb4 xiaozhi_esp32_server < list_ai_agent_ids.example.sql
--
-- 根据 intro_hint（角色介绍前 100 字）判断哪一条是你在智控台编辑的智能体。

SELECT
  id,
  CHAR_LENGTH(system_prompt) AS prompt_len,
  LEFT(system_prompt, 100) AS intro_hint
FROM ai_agent;

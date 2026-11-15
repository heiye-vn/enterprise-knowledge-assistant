# 简易本地登录配置

2026-11-14，按用户要求统一简化本地开发凭证。PostgreSQL 使用 postgres，RustFS 使用 admin，Neo4j 使用 neo4j，三项密码均为 12345678；Redis 无账号密码。地址和完整登录表见根 README。

已同步当前 .env、.env.example、后端 Settings 默认值和运行中的容器。init_env.py 改为复制文档化的本地配置，不再随机生成密码，仍保留已有 .env 和 0600 权限。修改前的配置私下备份在被 Git 忽略的 .local/env-backups/ 中。

PostgreSQL 已建立可用的 postgres 登录，保留已有数据库及原角色的对象归属。Neo4j 在现有数据库中修改实际密码；RustFS 用新环境凭证重建容器。没有删除数据卷，也没有重置数据库或对象桶。

Neo4j Browser 的公布连接地址同步为 neo4j://127.0.0.1:7694，HTTP 为 127.0.0.1:7484，避免浏览器使用另一个实例的默认 7687 端口。修改凭证期间浏览器旧连接重试曾触发临时登录限制，用户已用新凭证重新连接成功。

验证：新配置下后端 81 项测试通过，Ruff 与格式检查通过，ready 的四项依赖均正常；Worker inspect ping 返回 pong。RustFS 控制台实际登录成功，Neo4j 用户确认浏览器 Connected。临时目录验证 init_env.py 的新凭证和保留已有文件行为，无需新增低影响配置测试。

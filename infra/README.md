# 基础设施

已提供 [本地 Compose](compose.yaml)：API、Celery Worker、Outbox relay、迁移进程、独立 PostgreSQL 与 Redis。[Runner](../services/runner/README.md) 作为独立可信宿主进程运行，不向 API 容器挂载 Docker socket。

优先建立可复现的最小开发入口，不复制旧项目的 `.runtime`、凭据、验收网络或操作器脚本。

独立新库由本仓库迁移管理。Redis 负责任务唤醒与非权威缓存，业务真值位于 PostgreSQL；代码执行容器不连接业务数据库。

## 本地资源边界

- Compose 项目名固定为 `leornian`，独立 `leornian_postgres-data` 数据卷，不复用旧容器或网络。
- PostgreSQL/Redis/API 仅绑定 `127.0.0.1:5448/6388/8088`。
- `.env` 必须提供 `LEORNIAN_POSTGRES_PASSWORD`，由根目录启动说明生成且已忽略；不是生产凭据管理方案。
- 默认网络为 `10.83.44.0/24`，可设置 `LEORNIAN_SUBNET`。本机默认地址池耗尽，不能以清理旧网络来解决。
- 服务共同使用 `leornian-backend:dev` 镜像；先单独 `build api` 再 `up --no-build`，避免并行给同一个镜像重复打标签。
- Docker 构建使用 uv 缓存挂载，业务代码变化不必重复下载已缓存 Python 依赖；依赖仍以锁文件为准。
- `LEORNIAN_RUNNER_TOKEN` 是内部控制凭据，与 learner token 和模型密钥分开；仅传可信 API/控制进程，不传学习代码容器。
- 迁移成功后 API/Worker/relay 才启动。停止用 `stop`，保留数据库卷。

PostgreSQL/Redis 镜像使用主版本/补丁标签，未声称操作系统镜像已冻结到 digest。该 Compose 是本地开发入口，不是生产部署模板；生产数据库角色和公开入口需另行设计。

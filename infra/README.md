# 基础设施

已提供 [本地 Compose](compose.yaml)：API、Celery Worker、Outbox relay、迁移进程、独立 PostgreSQL 与 Redis。[Runner](../services/runner/README.md) 作为独立可信宿主进程运行，不向 API 容器挂载 Docker socket。

提供可复现的本地开发与验收入口，不复制旧项目的 `.runtime`、验收网络或操作器脚本；凭据复用按下述明确授权独立配置。

2026-11-03 产品边界：所有业务后台、数据和代码执行仅在用户本机，不提供托管服务器或远程 Runner；模型 API 仍按用户配置及用途联网。正式桌面应用应管理本地组件及引擎引导，课程环境按路线明确授权后按需准备，不修改全局 SDK；当前 Compose/终端流程只是开发入口，上述自动管理尚未交付，见 [第四阶段 IMP](../docs/phase-4/imp.md) WP11。

2026-10-31 用户另行授权复用旧仓库密钥；本机仅将需要的模型配置放到忽略的 `.env`，不迁移旧运行状态或数据库。Compose 将模型设置交给可信后端，不传给学习代码容器；不运行会打印解析后全部环境的 `compose config`。

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
- 模型容量可用 `LEORNIAN_MODEL_CONTEXT_TOKENS` / `LEORNIAN_MODEL_MAX_OUTPUT_TOKENS` 显式声明；默认 0 时从已认证 `/models` 发现，不假定所有通道支持该扩展。无法发现时等待正确配置，不回退到臆造的容量。阶段输出/总超时在 Runtime policy 解析并随调用冻结。
- Worker 对长请求独立心跳续租；Redis 可见性超时为 3600 秒，Worker 停止宽限为 650 秒。调度额度和租约不是任务总尝试上限；部署前核对在途调用，保留 UNKNOWN 和已有回执。

PostgreSQL/Redis 镜像使用主版本/补丁标签，未声称操作系统镜像已冻结到 digest。该 Compose 是本地开发入口，不是正式桌面发行方案；本机组件启停、升级/恢复、安全存储和安装权限须另行完成，不开放公网入口或追加远程执行模式。

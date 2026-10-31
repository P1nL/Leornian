# 隔离 Runner

`controller.py` 是可信本地控制进程：通过内部认证的 claim/report API 领取执行任务，启动受限 Docker 容器并回传结果。当前支持固定 Python 入门课，不提供任意语言、镜像或挂载参数。

可信控制进程与不可信学习代码分开：学习代码不能取得宿主凭据或业务库权限。执行受网络、文件系统、CPU、内存、进程数、时长和输出限制。

Runner 不裁定 Gate 或掌握度。结果先由 execution 记录，再由 assessment 裁定，最后由 learning 检查条件并应用进度。

## 启动

从仓库根目录用 PowerShell 7 执行。首次为本项目追加独立凭据，不读取旧 Aearn 设置：

```powershell
$path = Join-Path $PWD '.env'
$lines = [IO.File]::ReadAllLines($path)
if (-not ($lines | Where-Object { $_.StartsWith('LEORNIAN_RUNNER_TOKEN=') })) {
    $token = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    [IO.File]::AppendAllText($path, "`nLEORNIAN_RUNNER_TOKEN=$token`n")
}
# API 必须重新加载凭据。先按根 README 构建镜像，再启动服务。
docker compose --env-file .env -f infra/compose.yaml up -d --no-build api worker relay
$line = [IO.File]::ReadAllLines($path) | Where-Object { $_.StartsWith('LEORNIAN_RUNNER_TOKEN=') }
$env:LEORNIAN_RUNNER_TOKEN = $line.Substring($line.IndexOf('=') + 1)
& .\backend\.venv\Scripts\python.exe .\services\runner\controller.py
```

此进程持续运行，关闭终端或 Ctrl+C 停止。容器镜像默认 `python:3.12-slim`，必须已存在，运行时 `--pull=never`。可由可信操作者设置 `LEORNIAN_RUNNER_IMAGE` 和 `LEORNIAN_RUNNER_API`，不接受学习者指定。该标签未冻结 digest；公开生产执行还需独立沙箱和镜像审计。

## 隔离与故障

- 每个用例 6 秒、128MB、0.5 CPU、32 进程、nofile 64；stdout/stderr 各最多 4096 字节。
- `--network=none`、只读根目录、无宿主目录挂载、UID/GID 65534、移除全部 capabilities、no-new-privileges。
- 控制凭据只留父进程，不传入学习代码容器。Runner 不连接数据库，预期答案留服务端 assessment。
- 回报可重试最多三次，但不会重新执行同一代码；过期任务由 relay 关闭，不自动再领取。
- 每次只清理本进程生成随机名称的容器，不 prune 或影响其他项目。不能确认停止时控制器退出，不继续领取新作业。
- 真实 Docker 测试覆盖无凭据/网络/可写根目录、超时停止和输出上限；它不是所有容器逃逸攻击的证明，当前服务只限本地开发。

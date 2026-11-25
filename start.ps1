#Requires -Version 7.0
#Requires -PSEdition Core

[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipRunner,
    [ValidateRange(1, 65535)][int]$WebPort = 5180
)

$ErrorActionPreference = 'Stop'

function Get-ProjectRunner {
    param([string]$PythonPath, [string]$ControllerPath)

    $controllerArgument = [regex]::Escape($ControllerPath.Replace('/', '\'))
    $commandPattern = '^\s*(?:"[^"]+"|[^\s"]+)\s+(?:-u\s+)?(?:"' +
        $controllerArgument + '"|' + $controllerArgument + ')\s*$'
    Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object {
            $_.ExecutablePath -ieq $PythonPath -and
            $_.CommandLine -and $_.CommandLine.Replace('/', '\') -match $commandPattern
        } |
        Select-Object -First 1
}

foreach ($command in @('docker', 'pnpm')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing command: $command. Install the local prerequisites described in README.md."
    }
}

$runner = $null
$runnerStopFile = $null
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
        throw 'Missing .env. Complete the first-time setup in README.md before starting.'
    }

    & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker is unavailable. Start Docker Desktop with Linux containers and try again.'
    }

    $compose = @('compose', '--env-file', '.env', '-f', 'infra/compose.yaml')
    if (-not $SkipRunner) {
        $runnerPython = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $runnerPython -PathType Leaf)) {
            throw 'Missing project Python. Run: uv sync --directory backend --frozen (or use -SkipRunner for frontend-only work).'
        }

        # Use Compose's effective token, including dotenv quoting and environment overrides.
        $configuration = & docker @compose config --format json
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not read the Compose configuration for the local Runner.'
        }
        $runnerToken = ($configuration | ConvertFrom-Json).services.api.environment.LEORNIAN_RUNNER_TOKEN
        $configuration = $null
        if ([string]::IsNullOrWhiteSpace($runnerToken)) {
            throw 'Configure LEORNIAN_RUNNER_TOKEN as described in services/runner/README.md, or use -SkipRunner.'
        }
    }

    if ($Build) {
        Write-Host 'Building the backend...'
        & docker @compose build api
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend build failed.'
        }
    }

    Write-Host 'Starting the backend and waiting for readiness...'
    & docker @compose up -d --wait --wait-timeout 120 api worker material-worker relay
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend startup failed. Run: docker compose --env-file .env -f infra/compose.yaml logs --tail 100 api worker material-worker relay'
    }

    if ($Build -or -not (Test-Path -LiteralPath '.local/librechat-connected/dist/index.html' -PathType Leaf)) {
        Write-Host 'Building the web frontend...'
        & pnpm build
        if ($LASTEXITCODE -ne 0) {
            throw 'Web frontend build failed.'
        }
    }

    if (-not $SkipRunner) {
        $runnerController = Join-Path $PSScriptRoot 'services/runner/controller.py'
        $runnerDirectory = Join-Path $PSScriptRoot '.runtime/development-runner'
        [IO.Directory]::CreateDirectory($runnerDirectory) | Out-Null
        $runnerStopFile = Join-Path $runnerDirectory "$PID.stop"
        $runnerOutput = Join-Path $runnerDirectory "$PID.stdout.log"
        $runnerError = Join-Path $runnerDirectory "$PID.stderr.log"
        Remove-Item -LiteralPath $runnerStopFile -Force -ErrorAction SilentlyContinue
        $environment = @{
            LEORNIAN_RUNNER_TOKEN = $runnerToken
            LEORNIAN_RUNNER_API = 'http://127.0.0.1:8088'
            LEORNIAN_RUNNER_STOP_FILE = $runnerStopFile
        }
        $previousEnvironment = @{}
        try {
            foreach ($name in $environment.Keys) {
                $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
                [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
            }
            Write-Host 'Starting the local Runner controller...'
            $runner = Start-Process -FilePath $runnerPython `
                -ArgumentList @('-u', ('"{0}"' -f $runnerController)) `
                -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput $runnerOutput -RedirectStandardError $runnerError
        }
        finally {
            foreach ($name in $previousEnvironment.Keys) {
                $value = $previousEnvironment[$name]
                # Preserve absent variables instead of converting null to an empty string.
                if ($null -eq $value) {
                    $value = [NullString]::Value
                }
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
            $runnerToken = $null
        }
        Start-Sleep -Seconds 1
        if ($runner.HasExited) {
            $existingRunner = $null
            if ((Test-Path -LiteralPath $runnerError -PathType Leaf) -and
                [IO.File]::ReadAllText($runnerError).Trim() -eq
                    "This application's local controller is already running.") {
                $existingRunner = Get-ProjectRunner -PythonPath $runnerPython `
                    -ControllerPath $runnerController
            }
            if ($null -eq $existingRunner) {
                throw "Runner exited during startup. Check $runnerError and $runnerOutput. If a controller is already running, use -SkipRunner."
            }
            # Reuse does not transfer ownership of the existing controller's stop signal.
            $runner = $null
            Write-Host "Reusing this project's Runner: PID $($existingRunner.ProcessId). It will remain running when this script stops."
        }
        else {
            Write-Host "Runner: PID $($runner.Id); logs: $runnerDirectory"
        }
    }

    Write-Host "Web: http://127.0.0.1:$WebPort/c/new"
    Write-Host 'API: http://127.0.0.1:8088/health/ready'
    if ($null -ne $runner) {
        Write-Host 'Ctrl+C stops the web frontend and this script''s Runner. Backend services remain running.'
    }
    else {
        Write-Host 'Ctrl+C stops the web frontend. Existing Runner processes and backend services remain running.'
    }
    if ($WebPort -eq 5180) { & pnpm dev }
    else { & pnpm librechat:connected $WebPort }
    if ($LASTEXITCODE -ne 0) {
        throw "Web frontend exited with an error. Check the output above (including any port $WebPort conflict)."
    }
}
finally {
    try {
        if ($null -ne $runner -and -not $runner.HasExited) {
            Write-Host 'Stopping the local Runner and waiting for isolated-task cleanup...'
            [IO.File]::WriteAllText($runnerStopFile, 'stop')
            if (-not $runner.WaitForExit(20000)) {
                Write-Warning "Runner is still cleaning up. Keep the backend running and check $runnerDirectory before stopping it."
            }
        }
    }
    finally {
        Pop-Location
    }
}

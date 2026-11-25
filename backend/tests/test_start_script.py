import json
import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is not installed")

HARNESS = r"""
param([string]$Root, [string]$Scenario)
$ErrorActionPreference = 'Stop'
$global:events = [Collections.Generic.List[string]]::new()
$global:scenario = $Scenario
$global:runner = $null
$global:runnerConfigurationValid = $false
$global:runnerStopFile = $null
$global:parentEnvironment = @{
    LEORNIAN_RUNNER_TOKEN = $null
    LEORNIAN_RUNNER_API = $null
    LEORNIAN_RUNNER_STOP_FILE = $null
}
if ($Scenario -in @('build', 'spawn-failure')) {
    $global:parentEnvironment.LEORNIAN_RUNNER_TOKEN = 'parent-token'
    $global:parentEnvironment.LEORNIAN_RUNNER_API = 'http://localhost:9999'
    $global:parentEnvironment.LEORNIAN_RUNNER_STOP_FILE = 'parent-stop'
}
foreach ($name in $global:parentEnvironment.Keys) {
    if ($null -eq $global:parentEnvironment[$name]) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    else {
        [Environment]::SetEnvironmentVariable($name, $global:parentEnvironment[$name], 'Process')
    }
}

function docker {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') {
        $global:events.Add('docker-info')
        return 'linux'
    }
    if ($args -contains 'config') {
        $global:events.Add('config')
        $token = if ($global:scenario -eq 'missing-token') { '' } else { 'compose-test-token' }
        return @{services = @{api = @{environment = @{LEORNIAN_RUNNER_TOKEN = $token}}}} |
            ConvertTo-Json -Depth 6 -Compress
    }
    if ($args -contains 'up') {
        $global:events.Add('backend-up')
        if ($global:scenario -eq 'backend-failure') { $global:LASTEXITCODE = 1 }
        return
    }
    if ($args -contains 'build') {
        $global:events.Add('backend-build')
        return
    }
    throw 'Unexpected Docker command in test.'
}

function pnpm {
    $global:LASTEXITCODE = 0
    $global:events.Add("pnpm-$($args[0])")
    if ($global:scenario -in @('frontend-failure', 'runner-reused-frontend-failure') -and
        $args[0] -eq 'dev') {
        $global:LASTEXITCODE = 1
    }
}

function Start-Sleep {}

function Get-CimInstance {
    param($ClassName, $Filter)
    $global:events.Add('runner-lookup')
    if ($ClassName -ne 'Win32_Process' -or $Filter -ne "Name = 'python.exe'") {
        throw 'Runner lookup must inspect Python processes only.'
    }
    $python = Join-Path $Root 'backend/.venv/Scripts/python.exe'
    $controller = Join-Path $Root 'services/runner/controller.py'
    $executable = $python
    if ($global:scenario -eq 'runner-foreign-python') {
        $executable = Join-Path $Root 'other-project/python.exe'
    }
    if ($global:scenario -eq 'runner-foreign-controller') {
        $controller = Join-Path $Root 'other-project/controller.py'
    }
    $command = "`"$python`" -u `"$controller`""
    if ($global:scenario -eq 'runner-argument-only') {
        $command = "`"$python`" -c `"print('not a controller')`" `"$controller`""
    }
    if ($global:scenario -eq 'runner-reused-forward-slashes') {
        $command = $command.Replace('\', '/')
    }
    [pscustomobject]@{
        ProcessId = 56789
        ExecutablePath = $executable
        CommandLine = $command
    }
}

function Start-Process {
    param(
        $FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
        [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError
    )
    $global:events.Add('runner-start')
    $global:runnerStopFile = $env:LEORNIAN_RUNNER_STOP_FILE
    $global:runnerConfigurationValid = (
        $env:LEORNIAN_RUNNER_TOKEN -eq 'compose-test-token' -and
        $env:LEORNIAN_RUNNER_API -eq 'http://127.0.0.1:8088' -and
        $WorkingDirectory -eq $Root -and
        $FilePath -eq (Join-Path $Root 'backend/.venv/Scripts/python.exe') -and
        $ArgumentList[0] -eq '-u' -and
        $ArgumentList[1] -eq ('"{0}"' -f (Join-Path $Root 'services/runner/controller.py')) -and
        $WindowStyle -eq 'Hidden' -and $PassThru -and
        $RedirectStandardOutput.EndsWith('.stdout.log') -and
        $RedirectStandardError.EndsWith('.stderr.log')
    )
    if ($global:scenario -eq 'spawn-failure') { throw 'Simulated process startup failure.' }
    $duplicate = $global:scenario -like 'runner-*' -and $global:scenario -ne 'runner-exited'
    if ($duplicate) {
        [IO.File]::WriteAllText(
            $RedirectStandardError, "This application's local controller is already running.`n"
        )
    }
    $global:runner = [pscustomobject]@{
        Id = 12345
        HasExited = ($global:scenario -eq 'runner-exited' -or $duplicate)
    }
    $global:runner | Add-Member ScriptMethod WaitForExit {
        param($Milliseconds)
        if ($Milliseconds -ne 20000 -or -not (Test-Path -LiteralPath $global:runnerStopFile)) {
            throw 'Runner shutdown must signal before waiting for cleanup.'
        }
        $global:events.Add('runner-stop')
        if ($global:scenario -eq 'cleanup-timeout') { return $false }
        $this.HasExited = $true
        return $true
    }
    return $global:runner
}

$caller = Join-Path $Root 'caller'
Set-Location -LiteralPath $caller
$options = @{}
if ($Scenario -eq 'build') { $options.Build = $true }
if ($Scenario -eq 'skip') { $options.SkipRunner = $true }
$errorText = $null
try { & (Join-Path $Root 'start.ps1') @options }
catch { $errorText = $_.Exception.Message }
$environmentRestored = $true
foreach ($name in $global:parentEnvironment.Keys) {
    $actualValue = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ($actualValue -ne $global:parentEnvironment[$name]) {
        $environmentRestored = $false
    }
}
$result = @{
    events = @($global:events)
    error = $errorText
    runner_configuration_valid = $global:runnerConfigurationValid
    environment_restored = $environmentRestored
    directory_restored = ($PWD.Path -eq $caller)
}
Write-Output ('TEST_RESULT=' + ($result | ConvertTo-Json -Compress -Depth 5))
"""


@pytest.mark.parametrize(
    ("scenario", "events", "error"),
    [
        (
            "default",
            ["docker-info", "config", "backend-up", "runner-start", "pnpm-dev", "runner-stop"],
            None,
        ),
        (
            "build",
            [
                "docker-info",
                "config",
                "backend-build",
                "backend-up",
                "pnpm-build",
                "runner-start",
                "pnpm-dev",
                "runner-stop",
            ],
            None,
        ),
        ("skip", ["docker-info", "backend-up", "pnpm-dev"], None),
        ("missing-python", ["docker-info"], "Missing project Python"),
        ("missing-token", ["docker-info", "config"], "Configure LEORNIAN_RUNNER_TOKEN"),
        (
            "backend-failure",
            ["docker-info", "config", "backend-up"],
            "Backend startup failed",
        ),
        (
            "spawn-failure",
            ["docker-info", "config", "backend-up", "runner-start"],
            "Simulated process startup failure",
        ),
        (
            "runner-exited",
            ["docker-info", "config", "backend-up", "runner-start"],
            "Runner exited during startup",
        ),
        (
            "runner-reused",
            ["docker-info", "config", "backend-up", "runner-start", "runner-lookup", "pnpm-dev"],
            None,
        ),
        (
            "runner-reused-forward-slashes",
            ["docker-info", "config", "backend-up", "runner-start", "runner-lookup", "pnpm-dev"],
            None,
        ),
        (
            "runner-reused-frontend-failure",
            ["docker-info", "config", "backend-up", "runner-start", "runner-lookup", "pnpm-dev"],
            "Web frontend exited with an error",
        ),
        *[
            (
                scenario,
                ["docker-info", "config", "backend-up", "runner-start", "runner-lookup"],
                "Runner exited during startup",
            )
            for scenario in (
                "runner-foreign-python", "runner-foreign-controller", "runner-argument-only"
            )
        ],
        (
            "frontend-failure",
            ["docker-info", "config", "backend-up", "runner-start", "pnpm-dev", "runner-stop"],
            "Web frontend exited with an error",
        ),
        (
            "cleanup-timeout",
            ["docker-info", "config", "backend-up", "runner-start", "pnpm-dev", "runner-stop"],
            None,
        ),
    ],
)
def test_combined_startup(tmp_path, scenario, events, error):
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "caller").mkdir()
    (root / ".env").write_text("# No real credentials in launcher tests.\n", encoding="utf-8")
    frontend = root / ".local/librechat-connected/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").touch()
    if scenario not in {"missing-python", "skip"}:
        python = root / "backend/.venv/Scripts/python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
    shutil.copyfile(ROOT / "start.ps1", root / "start.ps1")
    harness = tmp_path / "test-start.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(harness), "-Root", str(root), "-Scenario", scenario],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("TEST_RESULT=")
    )
    result = json.loads(result_line.removeprefix("TEST_RESULT="))
    assert result["events"] == events
    assert result["directory_restored"]
    assert result["environment_restored"]
    if "runner-start" in events:
        assert result["runner_configuration_valid"]
    if error is None:
        assert result["error"] is None
    else:
        assert error in result["error"]
    assert "compose-test-token" not in completed.stdout + completed.stderr
    if scenario == "cleanup-timeout":
        assert "Runner is still cleaning up" in completed.stdout
    if scenario.startswith("runner-reused"):
        assert "Reusing this project's Runner: PID 56789" in completed.stdout
        assert "Existing Runner processes and backend services remain running." in completed.stdout
        assert "runner-stop" not in result["events"]

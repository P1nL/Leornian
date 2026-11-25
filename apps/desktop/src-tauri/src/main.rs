#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::Command;
use tauri::Manager;

fn hidden(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
}

fn resource_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let mut candidates = vec![
        app.path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("runtime"),
        std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("Application directory is unavailable.")?
            .join("runtime"),
    ];
    if let Some(path) = std::env::var_os("LEORNIAN_RESOURCE_DIRECTORY") {
        candidates.insert(0, PathBuf::from(path));
    }
    if cfg!(debug_assertions) {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(root) = source.ancestors().nth(3) {
            candidates.push(root.join(".local/native-package/runtime"));
        }
    }
    candidates
        .into_iter()
        .find(|path| path.join("runtime.json").is_file())
        .ok_or_else(|| "应用专用运行包缺失；请使用包含 runtime 目录的完整本机发行包。".to_owned())
}

fn run_services(app: &tauri::AppHandle, action: &str) -> Result<serde_json::Value, String> {
    if action == "engine_guide" {
        #[cfg(windows)]
        {
            let mut command = Command::new("rundll32.exe");
            command.args([
                "url.dll,FileProtocolHandler",
                "https://docs.docker.com/desktop/setup/install/windows-install/",
            ]);
            hidden(&mut command);
            command.spawn().map_err(|e| e.to_string())?;
            return Ok(serde_json::json!({"opened": true}));
        }
        #[cfg(not(windows))]
        return Err("请打开 Docker 官方安装说明完成本机隔离引擎安装。".to_owned());
    }
    if action == "engine_start" {
        let program_files =
            std::env::var_os("ProgramFiles").ok_or("Program Files is unavailable.")?;
        let executable = PathBuf::from(program_files).join("Docker/Docker/Docker Desktop.exe");
        if !executable.is_file() {
            return Err("本机隔离引擎尚未安装；请先查看官方安装说明。".to_owned());
        }
        let mut command = Command::new(executable);
        hidden(&mut command);
        command.spawn().map_err(|e| e.to_string())?;
        return Ok(serde_json::json!({"starting": true}));
    }
    if !["status", "start", "stop", "frontend"].contains(&action) {
        return Err("Unsupported local service action.".to_owned());
    }
    let resources = resource_root(app)?;
    let mut command = Command::new(resources.join("python/python.exe"));
    command
        .args([
            "-m",
            "leornian.bootstrap.local_services",
            action,
            "--resources",
        ])
        .arg(&resources)
        .current_dir(&resources)
        .env("PYTHONDONTWRITEBYTECODE", "1");
    hidden(&mut command);
    let output = command.output().map_err(|e| e.to_string())?;
    let body: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| "本机服务管理器没有返回完整状态。".to_owned())?;
    if !output.status.success() {
        return Err(body["error"]
            .as_str()
            .unwrap_or("本机服务操作未完成。")
            .to_owned());
    }
    Ok(body)
}

#[tauri::command]
async fn local_services(
    app: tauri::AppHandle,
    action: String,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_services(&app, &action))
        .await
        .map_err(|e| e.to_string())?
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![local_services])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Ok(status) = run_services(&handle, "frontend") {
                    if let Some(address) = status["frontend_url"].as_str() {
                        if let (Some(window), Ok(url)) = (
                            handle.get_webview_window("main"),
                            address.replace("/c/new", "/local-setup.html").parse(),
                        ) {
                            let _ = window.navigate(url);
                        }
                    }
                }
                if let Ok(status) = run_services(&handle, "start") {
                    if let Some(address) = status["frontend_url"].as_str() {
                        let target = if status["application"] == "ready" {
                            address.to_owned()
                        } else {
                            address.replace("/c/new", "/local-setup.html")
                        };
                        if let (Some(window), Ok(url)) =
                            (handle.get_webview_window("main"), target.parse())
                        {
                            let _ = window.navigate(url);
                        }
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Leornian desktop failed to start");
}

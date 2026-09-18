#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs;
use std::path::Path;
use tauri::api::process::{Command, CommandEvent};
use tauri::Manager;

#[tauri::command]
fn get_metabolism_state() -> String {
    let state_path = Path::new(".elora/state.json");
    if state_path.exists() {
        if let Ok(content) = fs::read_to_string(state_path) {
            return content;
        }
    }
    // Honest default state when state.json not yet written
    serde_json::json!({
        "state": 1,
        "state_name": "ALIVE",
        "chainOk": 1.0,
        "cpuLimit": 10.0,
        "ram_hard_cap_mb": 8064
    }).to_string()
}

#[tauri::command]
fn trigger_ripple(organ: String, kind: String) -> Result<String, String> {
    let payload = serde_json::json!({
        "organ": organ,
        "kind": kind,
        "ts": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64()
    });

    let shm_dir = Path::new(".elora/shm");
    if !shm_dir.exists() {
        let _ = fs::create_dir_all(shm_dir);
    }
    let fallback = Path::new(".elora/shm/overlay.ring.json");
    let _ = fs::write(fallback, payload.to_string());
    Ok(format!("{}.{}", organ, kind))
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let app_handle = app.handle();
            // Sidecar spawning logic
            tauri::async_runtime::spawn(async move {
                let res = Command::new("python")
                    .args(["run.py", "--brain", "bitnet"])
                    .spawn();
                if let Ok((mut rx, _child)) = res {
                    while let Some(event) = rx.recv().await {
                        if let CommandEvent::Stdout(line) = event {
                            println!("[sidecar] {}", line);
                            // Emit ripple to webview if app window is open
                            if let Some(window) = app_handle.get_window("main") {
                                let _ = window.emit("ripple", &line);
                            }
                        }
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_metabolism_state,
            trigger_ripple
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

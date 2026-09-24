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
    serde_json::json!({
        "state": 1,
        "state_name": "ALIVE",
        "chainOk": 1.0,
        "cpuLimit": 10.0,
        "ram_hard_cap_mb": 8064
    }).to_string()
}

#[tauri::command]
fn get_now_state() -> String {
    let state_path = Path::new(".elora/state.json");
    if state_path.exists() {
        if let Ok(content) = fs::read_to_string(state_path) {
            return content;
        }
    }
    serde_json::json!({
        "current_task": "Idle",
        "current_capability": "none",
        "status": "IDLE",
        "tier": "QUARANTINE",
        "last_action": "idle",
        "state_name": "ALIVE"
    }).to_string()
}

#[tauri::command]
fn get_ledger_tail() -> String {
    let tail_path = Path::new(".elora/ledger_tail.json");
    if tail_path.exists() {
        if let Ok(content) = fs::read_to_string(tail_path) {
            return content;
        }
    }
    "[]".to_string()
}

#[tauri::command]
fn get_chat_history() -> String {
    let chat_path = Path::new(".elora/chat.json");
    if chat_path.exists() {
        if let Ok(content) = fs::read_to_string(chat_path) {
            return content;
        }
    }
    "[]".to_string()
}

#[tauri::command]
fn send_inbox_task(prompt: String) -> Result<String, String> {
    let inbox_dir = Path::new(".elora/inbox");
    if !inbox_dir.exists() {
        let _ = fs::create_dir_all(inbox_dir);
    }
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let filename = format!("chat_{}.txt", ts);
    let target = inbox_dir.join(&filename);
    fs::write(&target, prompt.trim()).map_err(|e| e.to_string())?;

    let chat_path = Path::new(".elora/chat.json");
    let mut messages: Vec<serde_json::Value> = if chat_path.exists() {
        fs::read_to_string(chat_path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    } else {
        Vec::new()
    };
    messages.push(serde_json::json!({
        "sender": "user",
        "text": prompt.trim(),
        "task_id": filename,
        "ts": (ts as f64) / 1000.0,
        "status": "queued"
    }));
    let _ = fs::write(chat_path, serde_json::to_string_pretty(&messages).unwrap_or_default());

    Ok(filename)
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
            // Sidecar spawning logic: run with local brain
            tauri::async_runtime::spawn(async move {
                let res = Command::new("python")
                    .args(["run.py", "--brain", "local"])
                    .spawn();
                if let Ok((mut rx, _child)) = res {
                    while let Some(event) = rx.recv().await {
                        if let CommandEvent::Stdout(line) = event {
                            println!("[resident:sidecar] {}", line);
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
            get_now_state,
            get_ledger_tail,
            get_chat_history,
            send_inbox_task,
            trigger_ripple
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

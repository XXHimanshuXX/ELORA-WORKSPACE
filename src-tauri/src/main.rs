#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs;
use std::path::{Path, PathBuf};
use tauri::api::process::{Command, CommandEvent};
use tauri::Manager;

/// The port the console server listens on.
///
/// `tauri.conf.json` points the window at this same address, which is what keeps
/// the webview same-origin with its API. That matters: the console sets a custom
/// `X-ELORA-Client` header on every call, and a cross-origin request carrying a
/// custom header needs a CORS preflight, which the server refuses by design as
/// its CSRF defence. Loading the window from the bundled `tauri://` assets would
/// therefore have broken every data panel in the desktop build.
const CONSOLE_PORT: u16 = 8765;

/// Locate a file inside the project's `.elora` directory.
///
/// The previous implementation read `.elora/state.json` relative to the process
/// working directory. Under `cargo tauri dev` that directory is `src-tauri/`, so
/// the file was never found, and both state commands fell through to a hardcoded
/// `state_name: "ALIVE", chainOk: 1.0`. The window consequently reported a
/// healthy organism whether or not one was running — the precise failure mode
/// this project was built to stop.
///
/// This walks up from both the working directory and the executable directory,
/// and returns None rather than inventing a value.
fn elora_file(name: &str) -> Option<PathBuf> {
    let mut starts: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            starts.push(dir.to_path_buf());
        }
    }

    for start in starts {
        let mut cursor: Option<&Path> = Some(start.as_path());
        for _ in 0..5 {
            match cursor {
                Some(dir) => {
                    let candidate = dir.join(".elora").join(name);
                    if candidate.is_file() {
                        return Some(candidate);
                    }
                    cursor = dir.parent();
                }
                None => break,
            }
        }
    }
    None
}

/// What every reader returns when there is nothing to report.
///
/// `available: false` carries the reason with it, so a missing file cannot be
/// rendered downstream as a healthy zero.
fn unavailable(reason: &str) -> serde_json::Value {
    serde_json::json!({ "available": false, "reason": reason })
}

/// Read one `.elora` JSON file, reporting absence or a parse failure as such.
fn read_elora_json(name: &str) -> serde_json::Value {
    let path = match elora_file(name) {
        Some(path) => path,
        None => {
            return unavailable(&format!(
                "no .elora/{name} reachable from the working directory or beside the executable"
            ))
        }
    };

    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(err) => return unavailable(&format!("{} could not be read: {err}", path.display())),
    };

    // A file that is present but unparseable is still reported as present, with
    // its raw text, rather than being dropped into a misleading empty state.
    let data: serde_json::Value =
        serde_json::from_str(&text).unwrap_or_else(|_| serde_json::Value::String(text.clone()));

    serde_json::json!({
        "available": true,
        "path": path.to_string_lossy(),
        "data": data,
    })
}

#[tauri::command]
fn get_metabolism_state() -> serde_json::Value {
    read_elora_json("state.json")
}

#[tauri::command]
fn get_now_state() -> serde_json::Value {
    // Deliberately the same source as the metabolism command. The daemon writes
    // one state file; exposing two names for it is a naming difference, not a
    // data difference, and the UI says so rather than implying two sources.
    read_elora_json("state.json")
}

#[tauri::command]
fn get_ledger_tail() -> serde_json::Value {
    read_elora_json("ledger_tail.json")
}

#[tauri::command]
fn get_chat_history() -> serde_json::Value {
    read_elora_json("chat.json")
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
    let filename = format!("chat_{ts}.txt");
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
    let _ = fs::write(
        chat_path,
        serde_json::to_string_pretty(&messages).unwrap_or_default(),
    );

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
            // The console server. The window's URL points at it, so this has to
            // start first; the frontend tolerates the race by retrying health
            // before it declares the server down.
            let console_handle = app.handle();
            tauri::async_runtime::spawn(async move {
                let port = CONSOLE_PORT.to_string();
                let args = vec![
                    "-m",
                    "elora.dashboard.server",
                    "--port",
                    port.as_str(),
                    "--announce",
                ];
                if let Ok((mut rx, _child)) = Command::new("python").args(args).spawn() {
                    while let Some(event) = rx.recv().await {
                        if let CommandEvent::Stdout(line) = event {
                            println!("[console:server] {line}");
                            if let Some(window) = console_handle.get_window("main") {
                                let _ = window.emit("ripple", &line);
                            }
                        }
                    }
                }
            });

            // The resident brain, kept as its own process so the daemon keeps
            // running even if the console server is restarted. Its stdout is what
            // the `ripple` event carries to the overlay.
            let brain_handle = app.handle();
            tauri::async_runtime::spawn(async move {
                let args = vec!["run.py", "--brain", "omniroute"];
                if let Ok((mut rx, _child)) = Command::new("python").args(args).spawn() {
                    while let Some(event) = rx.recv().await {
                        if let CommandEvent::Stdout(line) = event {
                            println!("[resident:sidecar] {line}");
                            if let Some(window) = brain_handle.get_window("main") {
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

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs;
use std::path::{Path, PathBuf};
use tauri::api::process::{Command, CommandEvent};

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
/// Locate the project root containing .elora directory.
fn elora_root() -> Option<PathBuf> {
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
                    if dir.join(".elora").is_dir() {
                        return Some(dir.to_path_buf());
                    }
                    cursor = dir.parent();
                }
                None => break,
            }
        }
    }
    None
}

/// Locate a file inside the project's `.elora` directory.
fn elora_file(name: &str) -> Option<PathBuf> {
    if let Some(root) = elora_root() {
        let candidate = root.join(".elora").join(name);
        if candidate.is_file() {
            return Some(candidate);
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

fn main() {
    tauri::Builder::default()
        .setup(|_app| {
            let root = elora_root().unwrap_or_else(|| PathBuf::from("."));

            // The console server. The window's URL points at it, so this has to
            // start first; the frontend tolerates the race by retrying health
            // before it declares the server down.
            let server_root = root.clone();
            tauri::async_runtime::spawn(async move {
                let port = CONSOLE_PORT.to_string();
                let args = vec![
                    "-u",
                    "-m",
                    "elora.dashboard.server",
                    "--port",
                    port.as_str(),
                    "--announce",
                ];
                let cmd = Command::new("python").current_dir(server_root).args(args);
                if let Ok((mut rx, _child)) = cmd.spawn() {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                println!("[console:server] {line}");
                            }
                            CommandEvent::Stderr(line) => {
                                eprintln!("[console:server:err] {line}");
                            }
                            _ => {}
                        }
                    }
                }
            });

            // The resident brain is its own process so it can outlive a console
            // server restart. Its logs stay in the process output; the Resident
            // timeline is populated by persisted chat/Akashic evidence instead.
            let brain_root = root.clone();
            tauri::async_runtime::spawn(async move {
                // The Tauri host already owns the console server; start only
                // the resident process here, using the same local brain as the
                // documented restart path.
                let args = vec!["-u", "run.py", "--brain", "bitnet"];
                let cmd = Command::new("python").current_dir(brain_root).args(args);
                if let Ok((mut rx, _child)) = cmd.spawn() {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                println!("[resident:sidecar] {line}");
                            }
                            CommandEvent::Stderr(line) => {
                                eprintln!("[resident:sidecar:err] {line}");
                            }
                            _ => {}
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
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

/// How many times a crashed child is brought back before the shell gives up.
///
/// A resident that dies and stays dead is not a resident. The bound matters as
/// much as the restart: a permanent fault (an interpreter that is not there, a
/// state directory that cannot be written) would otherwise spin forever and
/// flood the log with the same line.
const MAX_RESTARTS: u32 = 3;

/// Pause before a restart, so a fast crash loop cannot saturate the machine.
const RESTART_DELAY_MS: u64 = 2_000;

/// The interpreter the Python side is run with.
///
/// On Windows a bare `python` can resolve to the Microsoft Store stub, which
/// opens the Store and exits non-zero instead of running anything. `ELORA_PYTHON`
/// lets a machine with several interpreters name the right one explicitly.
fn python_program() -> String {
    std::env::var("ELORA_PYTHON").unwrap_or_else(|_| "python".to_string())
}

/// Locate the project root containing the .elora directory.
///
/// The previous implementation read `.elora/state.json` relative to the process
/// working directory. Under `cargo tauri dev` that directory is `src-tauri/`, so
/// the file was never found, and both state commands fell through to a hardcoded
/// `state_name: "ALIVE", chainOk: 1.0`. The window consequently reported a
/// healthy organism whether or not one was running — the precise failure mode
/// this project was built to stop.
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

/// Which child a report belongs to.
#[derive(Clone, Copy)]
enum Role {
    Console,
    Resident,
}

impl Role {
    /// The log prefix this role has always used.
    fn label(self) -> &'static str {
        match self {
            Role::Console => "console:server",
            Role::Resident => "resident:sidecar",
        }
    }

    fn slot<'a>(self, report: &'a mut ShellReport) -> &'a mut ChildReport {
        match self {
            Role::Console => &mut report.console,
            Role::Resident => &mut report.resident,
        }
    }
}

/// One child process, as it actually is.
///
/// `status` only ever holds a value this host has observed. It is never set to
/// `running` because a spawn was merely attempted, only because one succeeded —
/// the same rule the state commands above follow.
#[derive(Clone, Default, serde::Serialize)]
struct ChildReport {
    program: String,
    status: String,
    pid: Option<u32>,
    detail: Option<String>,
    restarts: u32,
}

/// The shell's own state, as opposed to the organism's.
#[derive(Clone, Default, serde::Serialize)]
struct ShellReport {
    console: ChildReport,
    resident: ChildReport,
}

/// Persist the shell's own state, so a dead window has a written reason.
///
/// `.elora/state.json` belongs to the daemon and is written by it;
/// `.elora/tauri_shell.json` belongs to this host. Neither overwrites the other,
/// so "the organism is not reporting" and "the shell could not bring the
/// organism up" stay distinguishable.
fn publish(root: &Path, report: &ShellReport) {
    let dir = root.join(".elora");
    if let Err(err) = fs::create_dir_all(&dir) {
        eprintln!("[shell] cannot create {}: {err}", dir.display());
        return;
    }
    match serde_json::to_string_pretty(report) {
        Ok(text) => {
            if let Err(err) = fs::write(dir.join("tauri_shell.json"), text) {
                eprintln!("[shell] cannot write tauri_shell.json: {err}");
            }
        }
        Err(err) => eprintln!("[shell] cannot encode the shell report: {err}"),
    }
}

/// Run one child, reporting what actually happened, and bring it back if it
/// crashes.
///
/// The previous version discarded the `Result` from `spawn()`. When `python` was
/// not resolvable, both children failed silently: the console server never bound
/// its port, the window loaded `http://127.0.0.1:8765/` into a refused
/// connection, and nothing anywhere said why. That is the failure this function
/// exists to make impossible — a spawn failure now reaches stderr and
/// `.elora/tauri_shell.json` carrying the program and the reason.
async fn supervise(
    role: Role,
    program: String,
    root: PathBuf,
    base_args: Vec<String>,
    report: Arc<Mutex<ShellReport>>,
) {
    let mut restarts: u32 = 0;

    loop {
        {
            let mut guard = report.lock().unwrap_or_else(|err| err.into_inner());
            let slot = role.slot(&mut guard);
            slot.program = program.clone();
            slot.status = "starting".to_string();
            slot.pid = None;
            slot.detail = None;
            slot.restarts = restarts;
            publish(&root, &guard);
        }

        let cmd = Command::new(program.clone())
            .current_dir(root.clone())
            .args(base_args.clone());

        let (mut rx, child) = match cmd.spawn() {
            Ok(pair) => pair,
            Err(err) => {
                let detail = format!("{program} could not be started: {err}");
                eprintln!("[{}] {detail}", role.label());
                let mut guard = report.lock().unwrap_or_else(|err| err.into_inner());
                let slot = role.slot(&mut guard);
                slot.status = "failed".to_string();
                slot.pid = None;
                slot.detail = Some(detail);
                publish(&root, &guard);
                return;
            }
        };

        {
            // The pid is taken from the handle, not assumed: this line is only
            // reached once the process genuinely exists.
            let mut guard = report.lock().unwrap_or_else(|err| err.into_inner());
            let slot = role.slot(&mut guard);
            slot.status = "running".to_string();
            slot.pid = Some(child.pid());
            publish(&root, &guard);
        }

        let mut exit_code: Option<i32> = None;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => println!("[{}] {line}", role.label()),
                CommandEvent::Stderr(line) => eprintln!("[{}:err] {line}", role.label()),
                CommandEvent::Error(err) => eprintln!("[{}:err] {err}", role.label()),
                CommandEvent::Terminated(payload) => exit_code = payload.code,
                // `CommandEvent` is `#[non_exhaustive]`; an event this build does
                // not know about is not a reason to stop supervising the child.
                _ => {}
            }
        }

        // A clean exit is the operator asking to stop. Only a crash is restarted.
        let crashed = exit_code != Some(0);
        if !crashed || restarts >= MAX_RESTARTS {
            let detail = match exit_code {
                Some(code) => format!("exited with code {code} after {restarts} restart(s)"),
                None => format!("terminated without an exit code after {restarts} restart(s)"),
            };
            eprintln!("[{}] {detail}", role.label());
            let mut guard = report.lock().unwrap_or_else(|err| err.into_inner());
            let slot = role.slot(&mut guard);
            slot.status = if crashed {
                "gave-up".to_string()
            } else {
                "exited".to_string()
            };
            slot.pid = None;
            slot.detail = Some(detail);
            publish(&root, &guard);
            return;
        }

        restarts += 1;
        eprintln!(
            "[{}] crashed with code {}; restart {restarts}/{MAX_RESTARTS} in {RESTART_DELAY_MS}ms",
            role.label(),
            exit_code.unwrap_or(-1)
        );

        // Slept off the async worker: `tauri::async_runtime` re-exports tokio's
        // channels and locks but not its timers, and blocking a runtime thread on
        // a timer stalls every other task scheduled on it.
        let _ = tauri::async_runtime::spawn_blocking(|| {
            std::thread::sleep(Duration::from_millis(RESTART_DELAY_MS))
        })
        .await;
    }
}

fn main() {
    let report = Arc::new(Mutex::new(ShellReport::default()));

    tauri::Builder::default()
        .setup(move |_app| {
            let root = elora_root().unwrap_or_else(|| PathBuf::from("."));
            let program = python_program();
            eprintln!("[shell] running the Python side with: {program}");

            // The console server. The window's URL points at it, so this has to
            // start first; the frontend tolerates the race by retrying health
            // before it declares the server down.
            //
            // This host owns the console server outright. The browser-oriented
            // resident entrypoint on `run.py` starts one as well, which is why it
            // is not used here: doing both would leave two servers racing for one
            // port, and whichever lost would take the window down with it.
            let console_args: Vec<String> = vec![
                "-u".to_string(),
                "-m".to_string(),
                "elora.dashboard.server".to_string(),
                "--port".to_string(),
                CONSOLE_PORT.to_string(),
                "--announce".to_string(),
            ];
            {
                let root = root.clone();
                let program = program.clone();
                let report = Arc::clone(&report);
                tauri::async_runtime::spawn(async move {
                    supervise(Role::Console, program, root, console_args, report).await;
                });
            }

            // The resident brain is its own process so it can outlive a console
            // server restart. Its logs stay in the process output; the Resident
            // timeline is populated by persisted chat/Akashic evidence instead.
            //
            // BitNet is pinned deliberately: it is the bundled local brain, so the
            // desktop shell still has a working resident on a machine with no
            // network and no OLLAMA daemon.
            let args = vec!["-u", "run.py", "--brain", "bitnet"];
            {
                let root = root.clone();
                let program = program.clone();
                let report = Arc::clone(&report);
                let args: Vec<String> = args.into_iter().map(String::from).collect();
                tauri::async_runtime::spawn(async move {
                    supervise(Role::Resident, program, root, args, report).await;
                });
            }

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

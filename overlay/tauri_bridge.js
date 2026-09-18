// overlay/tauri_bridge.js — Tauri Webview JS bridge for ELORA OS.

export function initTauriBridge(callbacks = {}) {
  const { onStateUpdate, onRipple } = callbacks;

  if (typeof window === "undefined" || !window.__TAURI__) {
    // Running in standalone browser or headless mock
    return { isTauri: false };
  }

  const tauri = window.__TAURI__;
  const invoke = tauri.invoke || (tauri.tauri && tauri.tauri.invoke);
  const listen = tauri.event && tauri.event.listen;

  // Poll metabolism state every 500ms
  const intervalId = setInterval(async () => {
    if (!invoke) return;
    try {
      const stateStr = await invoke("get_metabolism_state");
      const stateObj = typeof stateStr === "string" ? JSON.parse(stateStr) : stateStr;
      if (onStateUpdate) {
        onStateUpdate(stateObj);
      }
    } catch (err) {
      // Degrades silently if backend is starting
    }
  }, 500);

  // Listen for ripple events from daemon/sidecar
  let unlistenRipple = null;
  if (listen) {
    listen("ripple", (event) => {
      if (onRipple) {
        onRipple(event.payload);
      }
    }).then((unlisten) => {
      unlistenRipple = unlisten;
    }).catch(() => {});
  }

  return {
    isTauri: true,
    cleanup: () => {
      clearInterval(intervalId);
      if (unlistenRipple) unlistenRipple();
    }
  };
}

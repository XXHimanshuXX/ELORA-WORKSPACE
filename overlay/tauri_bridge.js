// overlay/tauri_bridge.js — Tauri Webview JS bridge for ELORA OS.

export function initTauriBridge(callbacks = {}) {
  const { onStateUpdate } = callbacks;

  if (typeof window === "undefined" || !window.__TAURI__) {
    // Running in standalone browser or headless mock
    return { isTauri: false };
  }

  const tauri = window.__TAURI__;
  const invoke = tauri.invoke || (tauri.tauri && tauri.tauri.invoke);

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

  return {
    isTauri: true,
    getChatHistory: async () => {
      if (!invoke) return null;
      try {
        const res = await invoke("get_chat_history");
        return typeof res === "string" ? JSON.parse(res) : res;
      } catch (err) {
        return null;
      }
    },
    cleanup: () => {
      clearInterval(intervalId);
    }
  };
}

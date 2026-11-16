// Your settings, loaded once and kept in step with the server.
import { api } from "./api.js";

let cache = null;

export async function loadPrefs(force = false) {
  if (!cache || force) cache = await api("/settings");
  return cache;
}

export async function patchPrefs(patch) {
  cache = await api("/settings", { method: "PATCH", body: patch });
  applyLook(cache);
  return cache;
}

export function applyLook(_prefs) {
  // Filled in with accent, cover size and titles (milestone 2, task 7).
}

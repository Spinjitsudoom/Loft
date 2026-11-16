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

export const ACCENTS = { brass: "#c9a27a", sage: "#a3b78f", dusk: "#97a9cc", rose: "#d39b9e", lilac: "#b8a0d0" };
const COVER_WIDTHS = { small: [108, 88], medium: [132, 104], large: [160, 124] };

export function applyLook(prefs) {
  if (!prefs) return;
  const look = prefs.look;
  const root = document.documentElement.style;
  root.setProperty("--brass", ACCENTS[look.accent] || ACCENTS.brass);
  const [desk, phone] = COVER_WIDTHS[look.cover_size] || COVER_WIDTHS.medium;
  root.setProperty("--cw", `${desk}px`);
  root.setProperty("--cw-phone", `${phone}px`);
  document.body.classList.toggle("no-cover-titles", !look.cover_titles);
}

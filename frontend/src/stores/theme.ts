import { create } from "zustand";

type Theme = "light" | "dark";

/** localStorage key — new mechanism (was "seerflow.theme") */
const STORAGE_KEY = "seerflow-theme";

/** Read persisted theme; default is dark (no class on <html>). */
function readInitial(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "dark" || v === "light") return v;
  } catch {
    /* jsdom/SSR: no localStorage */
  }
  return "dark";
}

/**
 * Apply theme to <html> via .sf-light class.
 * Dark = no class (default), Light = .sf-light present.
 * Persists to localStorage and broadcasts a `seerflow-theme` event so
 * every toggle widget and Cytoscape/uPlot theme resolver stays in sync.
 */
function apply(theme: Theme): void {
  try {
    document.documentElement.classList.toggle("sf-light", theme === "light");
  } catch {
    /* non-DOM env */
  }
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
  try {
    window.dispatchEvent(
      new CustomEvent("seerflow-theme", { detail: { light: theme === "light" } }),
    );
  } catch {
    /* non-DOM env */
  }
}

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

const initial = readInitial();
apply(initial);

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initial,
  toggle: () => {
    const next: Theme = get().theme === "light" ? "dark" : "light";
    apply(next);
    set({ theme: next });
  },
}));

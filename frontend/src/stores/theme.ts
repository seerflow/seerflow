import { create } from "zustand";

type Theme = "light" | "dark";
const STORAGE_KEY = "seerflow.theme";

function readInitial(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "dark" || v === "light") return v;
  } catch {
    /* jsdom/SSR: no localStorage */
  }
  return "light";
}

function apply(theme: Theme): void {
  try {
    document.documentElement.dataset.theme = theme;
  } catch {
    /* non-DOM env */
  }
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore */
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

import { useState, useSyncExternalStore } from "react";

export type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "protein-detective-theme";

function getStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  function setTheme(next: Theme) {
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  }

  return { theme, setTheme };
}

function resolveDark(): boolean {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "dark") return true;
  if (attr === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function subscribeDarkTheme(update: () => void) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const observer = new MutationObserver(update);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  media.addEventListener("change", update);
  return () => {
    observer.disconnect();
    media.removeEventListener("change", update);
  };
}

export function useDarkTheme(): boolean {
  return useSyncExternalStore(subscribeDarkTheme, resolveDark);
}

export function initTheme() {
  applyTheme(getStoredTheme());
}

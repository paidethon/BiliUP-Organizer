import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "dark" | "light" | "system";
export type AppliedTheme = "dark" | "light";

const STORAGE_KEY = "biliup-theme";
const GLASS_KEY = "biliup-glass";
const DEFAULT_GLASS = 14;

export function applyGlass(px: number) {
  const clamped = Math.max(0, Math.min(24, Math.round(px)));
  document.documentElement.style.setProperty("--lumi-glass-blur", `${clamped}px`);
}

export function getGlass(): number {
  const stored = Number(localStorage.getItem(GLASS_KEY));
  return Number.isFinite(stored) && stored >= 0 ? stored : DEFAULT_GLASS;
}

export function setGlass(px: number) {
  localStorage.setItem(GLASS_KEY, String(Math.round(px)));
  applyGlass(px);
}

function resolve(choice: ThemeChoice): AppliedTheme {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function apply(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolve(choice);
}

/** Apply the persisted theme + glass blur once at boot (CSP forbids inline scripts). */
export function initTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  const choice: ThemeChoice =
    stored === "light" || stored === "system" || stored === "dark" ? stored : "dark";
  apply(choice);
  applyGlass(getGlass());
}

export function useTheme(): [ThemeChoice, AppliedTheme, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "system" || stored === "dark" ? stored : "dark";
  });
  const [applied, setApplied] = useState<AppliedTheme>(() => resolve(choice));

  useEffect(() => {
    apply(choice);
    setApplied(resolve(choice));
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onMedia = () => {
      if (choice === "system") {
        apply(choice);
        setApplied(resolve(choice));
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        const next = event.newValue as ThemeChoice;
        setChoice(next);
        apply(next);
        setApplied(resolve(next));
      }
    };
    media.addEventListener("change", onMedia);
    window.addEventListener("storage", onStorage);
    return () => {
      media.removeEventListener("change", onMedia);
      window.removeEventListener("storage", onStorage);
    };
  }, [choice]);

  const update = useCallback((next: ThemeChoice) => {
    localStorage.setItem(STORAGE_KEY, next);
    setChoice(next);
    apply(next);
    setApplied(resolve(next));
  }, []);

  return [choice, applied, update];
}

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "dark" | "light" | "system";
export type AppliedTheme = "dark" | "light";

const STORAGE_KEY = "biliup-theme";

function resolve(choice: ThemeChoice): AppliedTheme {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function apply(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolve(choice);
}

/** Apply the persisted theme once at boot (CSP forbids inline bootstrap scripts). */
export function initTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  const choice: ThemeChoice =
    stored === "light" || stored === "system" || stored === "dark" ? stored : "dark";
  apply(choice);
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

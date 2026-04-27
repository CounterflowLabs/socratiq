"use client";

import { useCallback, useSyncExternalStore } from "react";

export type AppTheme = "light" | "dark";

function readExplicitTheme(): AppTheme | null {
  if (typeof document === "undefined") return null;
  const theme = document.documentElement.dataset.theme;
  return theme === "light" || theme === "dark" ? theme : null;
}

export function resolveTheme(): AppTheme {
  const explicitTheme = readExplicitTheme();
  return explicitTheme ?? "light";
}

export function useResolvedTheme(): AppTheme {
  const subscribe = useCallback((cb: () => void) => {
    const cleanups: Array<() => void> = [];

    if (typeof MutationObserver !== "undefined" && typeof document !== "undefined") {
      const observer = new MutationObserver(() => cb());
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      cleanups.push(() => observer.disconnect());
    }

    return () => {
      cleanups.forEach((cleanup) => cleanup());
    };
  }, []);

  const getSnapshot = useCallback(() => resolveTheme(), []);
  const getServerSnapshot = useCallback((): AppTheme => "light", []);

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

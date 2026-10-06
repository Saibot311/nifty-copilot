import { useCallback, useSyncExternalStore } from "react";

/** A per-viewer choice kept in localStorage (a picked move size, a time
 *  window): read without an effect, so the server render and the first client
 *  render agree, and every component using the same key moves together. When
 *  storage is blocked the choice lasts the visit. */
const chosen = new Map<string, string>();
const listeners = new Set<() => void>();

function read(key: string): string | null {
  if (chosen.has(key)) return chosen.get(key)!;
  try { return localStorage.getItem(key); } catch { return null; }
}

function subscribe(f: () => void) {
  listeners.add(f);
  return () => { listeners.delete(f); };
}

export function useStored(key: string, fallback: string): [string, (v: string) => void] {
  const value = useSyncExternalStore(subscribe, () => read(key) ?? fallback, () => fallback);
  const set = useCallback((v: string) => {
    chosen.set(key, v);
    try { localStorage.setItem(key, v); } catch { /* remembered for this visit only */ }
    listeners.forEach((f) => f());
  }, [key]);
  return [value, set];
}

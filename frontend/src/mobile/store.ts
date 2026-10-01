/**
 * Only an anonymous id and the current session id are kept in localStorage.
 * No personal data (plate number etc.) is ever collected (PRD 4.4).
 */

const ANON_KEY = "vq.anon";
const SESSION_KEY = "vq.session";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage unavailable (private mode): the app still works for this page load
  }
}

function randomId(): string {
  // crypto.randomUUID needs a secure context; a phone on http://<LAN ip> does not have one
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function anonId(): string {
  const existing = read(ANON_KEY);
  if (existing) return existing;
  const fresh = `anon-${randomId()}`.slice(0, 64);
  write(ANON_KEY, fresh);
  return fresh;
}

export function storedSessionId(): number | null {
  const raw = read(SESSION_KEY);
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isInteger(n) ? n : null;
}

export function storeSessionId(id: number | null): void {
  write(SESSION_KEY, id === null ? null : String(id));
}

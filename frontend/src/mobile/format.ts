export function hhmm(value: string | number | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function mmss(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function minutes(n: number): string {
  return `${Math.round(n)}분`;
}

export function kw(n: number): string {
  return `${n.toFixed(n >= 100 ? 0 : 1)} kW`;
}

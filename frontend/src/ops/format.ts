export { hhmm, kw } from "../mobile/format";

/** A finished car still plugged in after this long counts as abandoned (PRD A-05). */
export const OVERSTAY_MIN = 5;

export function hms(value: string | number | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  return d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export interface LoadLevel {
  label: string;
  color: string;
  /** a banner is shown from 90% on */
  alarm: boolean;
}

/** PRD A-02 thresholds: 70% yellow, 90% orange, 100% red. The label always accompanies the colour. */
export function loadLevel(ratio: number): LoadLevel {
  if (ratio >= 1) return { label: "한계 초과", color: "#dc2626", alarm: true };
  if (ratio >= 0.9) return { label: "주의 · 출력 제어 중", color: "#f97316", alarm: true };
  if (ratio >= 0.7) return { label: "높음", color: "#eab308", alarm: false };
  return { label: "여유", color: "#059669", alarm: false };
}

/** "아이오닉 5 (예시)" -> "아이오닉 5": the (예시) mark stays in tooltips and the detail panel. */
export function shortModel(name: string): string {
  return name.replace(/\s*\(예시\)$/, "");
}

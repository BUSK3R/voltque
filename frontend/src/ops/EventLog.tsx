import type { StationEvent } from "../api";
import { hms, shortModel } from "./format";

type Tone = "neutral" | "ok" | "warn" | "danger";

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 border-slate-300",
  ok: "bg-emerald-50 text-emerald-800 border-emerald-300",
  warn: "bg-orange-50 text-orange-800 border-orange-300",
  danger: "bg-red-50 text-red-800 border-red-300",
};

interface Line {
  label: string;
  tone: Tone;
  text: string;
}

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

/** Operator-facing sentence for one simulator event. */
export function describe(e: StationEvent): Line {
  const who = e.session_id === null ? "" : `#${e.session_id} ${e.model_name ? shortModel(e.model_name) : ""}`.trim();
  const p = e.payload;
  const charger = num(p.charger_id);
  switch (e.type) {
    case "registered":
      return { label: "등록", tone: "neutral", text: `${who} 대기 등록 → 충전기 ${charger ?? "-"}번` };
    case "called":
      return { label: "호출", tone: "neutral", text: `${who} 호출 · 충전기 ${charger ?? "-"}번 (노쇼 유예 5분)` };
    case "started":
      return {
        label: "충전 시작",
        tone: "neutral",
        text: `${who} 충전 시작 · 충전기 ${charger ?? "-"}번${p.limited === true ? ` (출력 제한 ${Math.round(num(p.alloc_kw) ?? 0)}kW)` : ""}`,
      };
    case "limited":
      return {
        label: "출력 제한",
        tone: "warn",
        text: `${who} 출력을 ${Math.round(num(p.alloc_kw) ?? 0)}kW로 제한 — ${str(p.reason) ?? "부하 한도 보호"}`,
      };
    case "delayed":
      return { label: "시작 지연", tone: "warn", text: `${who} 시작 지연 — ${str(p.reason) ?? "부하 한도 보호"}` };
    case "no_show":
      return p.final === true
        ? { label: "노쇼", tone: "danger", text: `${who} 두 번째 노쇼 → 대기 종료` }
        : {
            label: "노쇼",
            tone: "danger",
            text: `${who} 호출 후 미진입 → 대기 맨 뒤로 (충전기 ${num(p.from_charger) ?? "-"}→${num(p.to_charger) ?? "-"}번)`,
          };
    case "done":
      return {
        label: "충전 완료",
        tone: "ok",
        text: `${who} 충전 완료 · 충전기 ${charger ?? "-"}번${p.parked === true ? " (차량 미이동)" : ""}`,
      };
    case "overstay":
      return { label: "방치", tone: "warn", text: `${who} 완료 후 5분 초과 — 충전기 ${charger ?? "-"}번 점유 중` };
    case "nudged":
      return { label: "알림", tone: "neutral", text: `${who} 운전자에게 이동 알림 전송` };
    case "left":
      return { label: "이동", tone: "ok", text: `${who} 차량 이동 (점유 ${num(p.dwell_min) ?? "-"}분)` };
    case "cancelled":
      return { label: "취소", tone: "neutral", text: `${who} 대기 취소` };
    default:
      return { label: e.type, tone: "neutral", text: who };
  }
}

/** Bottom log: queue, load control and abandoned-car records, newest first. */
export default function EventLog({ events }: { events: StationEvent[] }) {
  return (
    <ol
      data-testid="event-log"
      className="max-h-[88px] space-y-1 overflow-y-auto pr-1 text-sm min-[1700px]:max-h-[160px]"
      aria-label="알림·이벤트 로그"
    >
      {events.length === 0 && <li className="py-3 text-center text-slate-500">아직 이벤트가 없습니다.</li>}
      {events.map((e) => {
        const line = describe(e);
        return (
          <li key={e.seq} data-event-type={e.type} className="flex items-center gap-3">
            <time className="w-[4.5rem] shrink-0 tabular-nums text-slate-500">{hms(e.ts)}</time>
            <span
              className={`w-[5.5rem] shrink-0 rounded-full border px-2 py-0.5 text-center text-xs font-semibold ${TONE[line.tone]}`}
            >
              {line.label}
            </span>
            <span className="min-w-0 truncate text-slate-800">{line.text}</span>
          </li>
        );
      })}
    </ol>
  );
}

import { api, type LaneBlock, type Session } from "../api";
import { useSimNow } from "../feed";
import { hhmm, minutes } from "./format";
import { useMySession } from "./session";
import { Badge, CalcBasis, Card, ConfirmButton } from "./ui";

function blockLabel(b: LaneBlock, index: number): string {
  if (b.is_me) return "내 차례";
  if (b.kind === "charging") return "현재 충전";
  return `대기 ${index}`;
}

/** D-04: now marker -> vehicles in front -> my turn, as one horizontal timeline. */
function Timeline({ lane, nowMs }: { lane: LaneBlock[]; nowMs: number }) {
  let waitingIndex = 0;
  return (
    <ol className="flex items-stretch gap-1.5 overflow-x-auto pb-1" aria-label="대기 타임라인">
      <li className="flex min-w-14 flex-col items-center justify-center rounded-xl bg-slate-800 px-2 py-2 text-white">
        <span className="text-[10px] font-semibold uppercase">지금</span>
        <span className="text-sm font-bold tabular-nums">{hhmm(nowMs)}</span>
      </li>
      {lane.map((b) => {
        if (b.kind === "waiting" && !b.is_me) waitingIndex += 1;
        const label = blockLabel(b, waitingIndex);
        const span = Math.max(1, (Date.parse(b.end) - Date.parse(b.start)) / 60_000);
        return (
          <li
            key={b.session_id}
            style={{ flexGrow: Math.sqrt(span), minWidth: "4.75rem" }}
            className={`flex flex-col justify-center rounded-xl border px-2 py-2 ${
              b.is_me
                ? "border-emerald-600 bg-emerald-50 ring-2 ring-emerald-600"
                : "border-slate-300 bg-white"
            }`}
          >
            <span className={`text-xs font-bold ${b.is_me ? "text-emerald-800" : "text-slate-600"}`}>
              {label}
            </span>
            <span className="text-sm font-semibold tabular-nums">{hhmm(b.start)}</span>
            <span className="text-xs tabular-nums text-slate-500">~{hhmm(b.end)}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** M3. */
export default function Queue({ session }: { session: Session }) {
  const { clear } = useMySession();
  const now = useSimNow();
  const called = session.status === "called";
  const delayed = session.status === "waiting" && session.resume_at !== null;

  const cancel = async () => {
    try {
      await api.cancel(session.session_id);
    } finally {
      clear();
    }
  };

  return (
    <div className="space-y-3 pb-6">
      <Card className="text-center">
        <p className="text-sm text-slate-500">
          {session.charger_id}번 충전기 · {session.model_name}
        </p>
        <p className="mt-1 text-2xl font-bold">
          {called ? (
            "호출되었습니다"
          ) : (
            <>
              내 앞 <span className="text-emerald-700">{session.ahead}대</span>
            </>
          )}
        </p>
        <p className="mt-1 text-lg">
          {session.planned_start ? (
            <>
              예상 <b className="tabular-nums">{hhmm(session.planned_start)}</b> 시작
            </>
          ) : (
            "예상 시각 계산 중"
          )}
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-1.5">
          {called && <Badge tone="warn">호출됨 · 진입 필요</Badge>}
          {delayed && <Badge tone="warn">부하로 시작 지연</Badge>}
          {!called && !delayed && <Badge tone="info">대기 중</Badge>}
          {session.queue_pos !== null && !called && <Badge tone="neutral">대기 순번 {session.queue_pos}</Badge>}
        </div>
      </Card>

      <Card>
        <h2 className="mb-2 font-bold">타임라인</h2>
        {session.lane.length > 0 ? (
          <Timeline lane={session.lane} nowMs={now} />
        ) : (
          <p className="text-sm text-slate-500">타임라인을 계산 중입니다.</p>
        )}
        <p className="mt-2 text-xs text-slate-500">
          내 충전 예상 {minutes(session.calc.total_min)} · 목표 {session.soc_start}→{session.soc_target}%
        </p>
      </Card>

      <CalcBasis calc={session.calc} />
      <ConfirmButton label="대기 취소" confirmLabel="대기 취소하기" onConfirm={cancel} />
    </div>
  );
}

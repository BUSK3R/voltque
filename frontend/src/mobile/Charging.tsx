import { api, type Session } from "../api";
import { useSimNow } from "../feed";
import { hhmm, kw, mmss } from "./format";
import { useMySession } from "./session";
import { BatteryGauge, Badge, CalcBasis, Card, ConfirmButton } from "./ui";

/** M4. The countdown runs on the simulation clock, so it follows 1x / 10x / 60x. */
export default function Charging({ session }: { session: Session }) {
  const { clear } = useMySession();
  const now = useSimNow();
  const left = session.planned_end ? Date.parse(session.planned_end) - now : 0;
  const tapering = session.soc_current >= 80;
  const limited = session.alloc_kw !== null;

  const stop = async () => {
    try {
      await api.cancel(session.session_id);
    } finally {
      clear();
    }
  };

  return (
    <div className="space-y-3 pb-6">
      <Card>
        <div className="flex items-center gap-4">
          <BatteryGauge soc={session.soc_current} target={session.soc_target} />
          <div className="min-w-0 flex-1 pt-10 text-center">
            <p className="text-xs text-slate-500">남은 시간</p>
            <p className="text-4xl font-bold tabular-nums tracking-tight" aria-live="off">
              {mmss(left)}
            </p>
            <p className="mt-2 text-sm text-slate-600">
              목표 {session.soc_target}%
              {session.planned_end && <> · 종료 {hhmm(session.planned_end)}</>}
            </p>
            <p className="mt-2 text-lg font-semibold tabular-nums">{kw(session.current_kw)}</p>
            <div className="mt-1 flex flex-wrap justify-center gap-1.5">
              {limited ? <Badge tone="warn">출력 제한 중</Badge> : <Badge tone="ok">정상 출력</Badge>}
              {tapering && <Badge tone="warn">속도 감소 구간</Badge>}
            </div>
          </div>
        </div>
        <p
          className={`mt-3 rounded-lg px-3 py-2 text-sm ${
            tapering ? "bg-orange-50 font-semibold text-orange-800" : "bg-slate-50 text-slate-600"
          }`}
        >
          {tapering
            ? "80%를 넘어 이후 충전 속도가 줄어듭니다. 남은 시간이 조금 더 걸릴 수 있어요."
            : "▲ 80% 이후에는 충전 속도가 줄어듭니다."}
        </p>
      </Card>

      <CalcBasis calc={session.calc} />
      <ConfirmButton label="충전 중단" confirmLabel="충전 중단하기" onConfirm={stop} />
    </div>
  );
}

import { useNavigate } from "react-router-dom";

import type { Session } from "../api";
import { useFeed } from "./feed";
import { hhmm } from "./format";
import { useMySession } from "./session";
import { Badge, Button, Card } from "./ui";

/** M5. */
export default function Done({ session }: { session: Session }) {
  const navigate = useNavigate();
  const { snap } = useFeed();
  const { clear } = useMySession();

  const usedMin =
    session.actual_start && session.actual_end
      ? (Date.parse(session.actual_end) - Date.parse(session.actual_start)) / 60_000
      : null;

  const next = snap?.schedule.chargers
    .find((c) => c.charger_id === session.charger_id)
    ?.blocks.find((b) => b.kind === "waiting");
  const nextState = !next
    ? { tone: "ok" as const, text: "대기 중인 다음 차량이 없습니다." }
    : next.status === "called"
      ? { tone: "info" as const, text: "다음 대기자를 호출했습니다." }
      : { tone: "neutral" as const, text: "다음 대기자가 곧 호출됩니다." };

  const home = () => {
    clear();
    navigate("/m", { replace: true });
  };

  return (
    <div className="space-y-3 pb-6">
      <Card className="text-center">
        <p className="text-4xl">✅</p>
        <h2 className="mt-1 text-2xl font-bold">충전이 완료되었습니다</h2>
        <p className="mt-1 text-sm text-slate-500">
          {session.soc_start}% → {session.soc_target}% · {session.charger_id}번 충전기
        </p>
      </Card>

      <Card>
        <dl className="grid grid-cols-2 gap-3 text-center">
          <div>
            <dt className="text-xs text-slate-500">충전량</dt>
            <dd className="text-2xl font-bold tabular-nums">{session.charged_kwh.toFixed(1)} kWh</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">이용 시간</dt>
            <dd className="text-2xl font-bold tabular-nums">
              {usedMin === null ? "-" : `${Math.round(usedMin)}분`}
            </dd>
          </div>
        </dl>
        {session.actual_start && session.actual_end && (
          <p className="mt-2 text-center text-xs text-slate-500">
            {hhmm(session.actual_start)} ~ {hhmm(session.actual_end)}
          </p>
        )}
      </Card>

      <Card>
        <p className="font-semibold">차량을 이동해 주세요</p>
        <p className="mt-1 text-sm text-slate-600">
          다음 차량이 기다리고 있을 수 있어요. 충전이 끝나면 바로 자리를 비워 주세요.
        </p>
        <div className="mt-2">
          <Badge tone={nextState.tone}>{nextState.text}</Badge>
        </div>
      </Card>

      <Button onClick={home}>처음으로</Button>
    </div>
  );
}

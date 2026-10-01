import { Link } from "react-router-dom";

import type { Charger } from "../api";
import { useFeed } from "../feed";
import { hhmm, kw } from "./format";
import { pathFor, useMySession } from "./session";
import { Badge, Banner, Card } from "./ui";

function chargerState(c: Charger): { label: string; tone: "ok" | "neutral" | "danger" } {
  if (c.status === "fault") return { label: "점검 중", tone: "danger" };
  if (c.status === "charging") return { label: "충전 중", tone: "neutral" };
  if (c.status === "occupied") return { label: "차량 이동 대기", tone: "neutral" };
  if (c.queue_total > 0) {
    // empty, but somebody is already ahead of a newcomer: never advertise it as free
    const head = c.blocks.find((b) => b.kind === "waiting");
    if (head?.status === "called") return { label: "호출 대기", tone: "neutral" };
    if (head?.notice) return { label: "시작 지연", tone: "neutral" };
    return { label: "대기 중", tone: "neutral" };
  }
  return { label: "사용 가능", tone: "ok" };
}

function LoadBar({ now, contract, limit }: { now: number; contract: number; limit: number }) {
  const pct = contract > 0 ? (now / contract) * 100 : 0;
  // PRD A-02 thresholds: 70% yellow, 90% orange, 100% red
  const [bar, label] =
    pct >= 100
      ? ["bg-red-500", "한계 초과"]
      : pct >= 90
        ? ["bg-orange-500", "주의 · 출력 제어 중"]
        : pct >= 70
          ? ["bg-yellow-400", "높음"]
          : ["bg-emerald-500", "여유"];
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold text-slate-700">충전소 부하</span>
        <span className="tabular-nums text-slate-600">
          {kw(now)} / 계약 {contract.toFixed(0)} kW · <b>{label}</b>
        </span>
      </div>
      <div className="relative mt-2 h-3 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${bar} transition-[width] duration-500`} style={{ width: `${Math.min(pct, 100)}%` }} />
        <div
          className="absolute top-0 h-full w-0.5 bg-slate-700"
          style={{ left: `${(limit / contract) * 100}%` }}
          title="부하 한도"
        />
      </div>
    </div>
  );
}

export default function Home() {
  const { snap } = useFeed();
  const { session, endedMessage } = useMySession();

  if (!snap) return <p className="py-10 text-center text-slate-500">충전소 정보를 불러오는 중…</p>;
  const { schedule, load } = snap;
  const mine = session !== null; // the provider only keeps active or finished sessions

  return (
    <div className="space-y-3 pb-24">
      {endedMessage && (
        <Banner tone="info" label="안내">
          {endedMessage}
        </Banner>
      )}

      <Card>
        <LoadBar now={load.now_kw} contract={load.contract_kw} limit={load.limit_kw} />
      </Card>

      <h2 className="px-1 pt-1 text-sm font-semibold text-slate-600">충전기</h2>
      <ul className="space-y-2">
        {schedule.chargers.map((c) => {
          const st = chargerState(c);
          const idleNow = c.status === "idle" && c.queue_total === 0;
          return (
            <li key={c.charger_id}>
              <Card className="flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="whitespace-nowrap text-lg font-bold">
                      {c.charger_id}번 · {c.rated_kw} kW
                    </span>
                    <Badge tone={st.tone}>{st.label}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-slate-600">
                    대기 <b>{c.queue_total}</b>대
                  </p>
                </div>
                <div className="text-right text-sm">
                  <p className="text-slate-500">예상 빈 시각</p>
                  <p className="text-lg font-bold tabular-nums">
                    {idleNow ? "지금 바로" : hhmm(c.free_at)}
                  </p>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
      <p className="px-1 text-xs text-slate-500">
        차종·충전기 수치는 시연용 임의 예시값입니다. 개인정보(차량번호 등)는 수집하지 않습니다.
      </p>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-200 bg-white/95 p-3 backdrop-blur">
        <div className="mx-auto max-w-[480px]">
          {session !== null && mine ? (
            <Link
              to={pathFor(session.status)}
              className="flex min-h-12 items-center justify-center rounded-xl bg-emerald-600 text-base font-semibold text-white active:bg-emerald-700"
            >
              내 충전 보기
            </Link>
          ) : (
            <Link
              to="/m/register"
              className="flex min-h-12 items-center justify-center rounded-xl bg-emerald-600 text-base font-semibold text-white active:bg-emerald-700"
            >
              내 차량 등록
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

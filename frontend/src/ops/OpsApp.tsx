import type { ReactNode } from "react";

import { FeedProvider, useFeed } from "../feed";
import AlertsPanel, { alertCount } from "./AlertsPanel";
import EventLog from "./EventLog";
import Gantt from "./Gantt";
import KpiCards from "./KpiCards";
import LoadChart from "./LoadChart";
import LoadGauge from "./LoadGauge";
import TopBar from "./TopBar";

function Panel({
  title,
  note,
  children,
  className = "",
}: {
  title: string;
  note?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 ${className}`}>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-base font-bold text-slate-800">{title}</h2>
        {note && <span className="text-xs text-slate-500">{note}</span>}
      </div>
      {children}
    </section>
  );
}

function Dashboard() {
  const { snap, connected } = useFeed();

  return (
    <div className="min-h-screen min-w-[1280px] bg-slate-100 text-slate-900">
      <TopBar snap={snap} connected={connected} alerts={alertCount(snap, connected)} />
      <main className="mx-auto max-w-[1840px] space-y-4 p-4">
        <AlertsPanel snap={snap} connected={connected} />
        {snap ? (
          <>
            <KpiCards kpi={snap.kpi} chargers={snap.schedule.chargers.length} />
            <div className="grid grid-cols-[65fr_35fr] gap-4">
              <Panel title="실시간 간트차트" note="충전기별 현재 충전 + 대기 1·2">
                <Gantt schedule={snap.schedule} />
              </Panel>
              <div className="space-y-4">
                <Panel title="부하 게이지" note="현재 kW / 계약 kW">
                  <LoadGauge load={snap.load} />
                </Panel>
                <Panel title="부하 추이" note="제어 없음 vs VoltQueue 적용">
                  <LoadChart load={snap.load} />
                </Panel>
              </div>
            </div>
            <Panel title="알림·이벤트 로그" note="방치 차량 · 출력 제한 · 시작 지연 기록">
              <EventLog events={snap.events} />
            </Panel>
            <p className="pb-2 text-center text-xs text-slate-500">
              차종·충전기·전일 KPI 수치는 시연용 임의 예시값이며 실제 제원·실측이 아닙니다.
            </p>
          </>
        ) : (
          <p className="py-24 text-center text-slate-500">서버에 연결하는 중…</p>
        )}
      </main>
    </div>
  );
}

/** Operator PC dashboard (1440x900 / 1920x1080), PRD 4.3 and 5.2. Shares the mobile app's live feed. */
export default function OpsApp() {
  return (
    <FeedProvider>
      <Dashboard />
    </FeedProvider>
  );
}

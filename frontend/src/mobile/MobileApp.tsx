import type { ReactNode } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import type { Session, SessionStatus } from "../api";
import { Alerts } from "./Alerts";
import Charging from "./Charging";
import Done from "./Done";
import { FeedProvider, useFeed } from "./feed";
import Home from "./Home";
import Queue from "./Queue";
import Register from "./Register";
import { pathFor, SessionProvider, useMySession } from "./session";

/** Session pages: wait for the server copy, then redirect if the status belongs elsewhere. */
function SessionPage({
  statuses,
  children,
}: {
  statuses: SessionStatus[];
  children: (s: Session) => ReactNode;
}) {
  const { id, session } = useMySession();
  if (id === null) return <Navigate to="/m" replace />;
  if (session === null) return <p className="py-10 text-center text-slate-500">불러오는 중…</p>;
  if (!statuses.includes(session.status)) return <Navigate to={pathFor(session.status)} replace />;
  return <>{children(session)}</>;
}

function Header() {
  const { snap } = useFeed();
  const sim = snap?.sim;
  return (
    <header className="sticky top-0 z-20 bg-slate-900 px-4 py-3 text-white">
      <div className="mx-auto flex max-w-[480px] items-center justify-between gap-2">
        <Link to="/m" className="min-w-0">
          <span className="text-lg font-extrabold tracking-tight text-emerald-400">VoltQueue</span>
          <span className="ml-2 truncate text-sm text-slate-300">
            {snap?.schedule.station_name ?? ""}
          </span>
        </Link>
        {sim && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
              sim.running ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700 text-slate-300"
            }`}
          >
            {sim.running ? `시뮬레이션 ${sim.speed}x` : "정지"}
          </span>
        )}
      </div>
    </header>
  );
}

/** Driver mobile web (360px). Routes M1~M5 of PRD 5.1. */
export default function MobileApp() {
  return (
    <FeedProvider>
      <SessionProvider>
        <div className="min-h-screen bg-slate-100 text-slate-900">
          <Header />
          <main className="mx-auto max-w-[480px] space-y-3 px-4 py-3">
            <Alerts />
            <Routes>
              <Route index element={<Home />} />
              <Route path="register" element={<Register />} />
              <Route
                path="queue"
                element={
                  <SessionPage statuses={["waiting", "called"]}>
                    {(s) => <Queue session={s} />}
                  </SessionPage>
                }
              />
              <Route
                path="charging"
                element={
                  <SessionPage statuses={["charging"]}>
                    {(s) => <Charging session={s} />}
                  </SessionPage>
                }
              />
              <Route
                path="done"
                element={
                  <SessionPage statuses={["done"]}>{(s) => <Done session={s} />}</SessionPage>
                }
              />
              <Route path="*" element={<Navigate to="/m" replace />} />
            </Routes>
          </main>
        </div>
      </SessionProvider>
    </FeedProvider>
  );
}

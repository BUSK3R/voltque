import { useEffect, useRef, useState } from "react";

import { api, type SimSpeed, type Snapshot, type Vehicle } from "../api";
import { useSimNow } from "../feed";
import { hms } from "./format";

const SPEEDS: SimSpeed[] = [1, 10, 60];

/** Demo arrivals for the "차량 추가" button: [vehicle index in the master list, from %, to %]. */
const ADD_PRESETS: [number, number, number][] = [
  [0, 20, 90],
  [1, 10, 80],
  [3, 30, 80],
  [2, 20, 100],
  [4, 15, 80],
];

const BTN =
  "rounded-lg px-3 py-1.5 text-sm font-semibold ring-1 ring-slate-600 hover:bg-slate-700 disabled:opacity-50";

/** A-06: simulation time controls (1x/10x/60x, play/pause, scenario reset, add vehicle). */
export default function TopBar({
  snap,
  connected,
  alerts,
}: {
  snap: Snapshot | null;
  connected: boolean;
  alerts: number;
}) {
  const now = useSimNow();
  const sim = snap?.sim;
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [added, setAdded] = useState(0);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const askTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api
      .vehicles()
      .then(setVehicles)
      .catch(() => setVehicles([]));
    return () => window.clearTimeout(askTimer.current);
  }, []);

  const run = async (job: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await job();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "요청에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const speed = (sim?.speed ?? 1) as SimSpeed;

  const reset = () => {
    if (!asking) {
      setAsking(true);
      askTimer.current = window.setTimeout(() => setAsking(false), 4000);
      return;
    }
    window.clearTimeout(askTimer.current);
    setAsking(false);
    // reload the demo scenario at t=0 and leave the clock stopped, so the presenter starts it
    void run(() => api.sim.start(speed, "demo", false));
  };

  const addVehicle = () => {
    const [vi, s0, s1] = ADD_PRESETS[added % ADD_PRESETS.length];
    const vehicle = vehicles[vi % Math.max(1, vehicles.length)];
    if (!vehicle) return;
    void run(async () => {
      await api.createSession({
        vehicle_id: vehicle.vehicle_id,
        soc_start: s0,
        soc_target: s1,
        anon_user_id: `ops-demo-${added + 1}`,
        charger_id: null,
        enter_delay_min: 3,
      });
      setAdded((n) => n + 1);
    });
  };

  return (
    <header className="bg-slate-900 text-white">
      <div className="mx-auto flex max-w-[1840px] items-center justify-between gap-4 px-4 py-2.5">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-extrabold tracking-tight">
            <span className="text-emerald-400">VoltQueue</span> 관제
          </h1>
          <select
            aria-label="충전소 선택"
            className="rounded-lg bg-slate-800 px-2 py-1.5 text-sm ring-1 ring-slate-600"
            value="1"
            onChange={() => undefined}
          >
            <option value="1">{snap?.schedule.station_name ?? "충전소"}</option>
          </select>
          <span
            className="tabular-nums text-sm text-slate-300"
            data-testid="sim-clock"
            title="시뮬레이션 시각"
          >
            🕒 {hms(now)}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div role="group" aria-label="시연 배속" className="flex overflow-hidden rounded-lg ring-1 ring-slate-600">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={sim?.speed === s}
                disabled={busy || !sim}
                onClick={() => void run(() => api.sim.speed(s))}
                className={`px-3 py-1.5 text-sm font-semibold tabular-nums ${
                  sim?.speed === s ? "bg-emerald-500 text-slate-900" : "hover:bg-slate-700"
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={busy || !sim}
            onClick={() => void run(() => (sim?.running ? api.sim.pause() : api.sim.start(speed)))}
            className={BTN}
            data-testid="sim-toggle"
          >
            {sim?.running ? "⏸ 일시정지" : "▶ 시작"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={reset}
            className={`${BTN} ${asking ? "bg-red-600 ring-red-400 hover:bg-red-700" : ""}`}
            data-testid="sim-reset"
          >
            {asking ? "한 번 더 누르면 리셋" : "↺ 시나리오 리셋"}
          </button>
          <button
            type="button"
            disabled={busy || vehicles.length === 0}
            onClick={addVehicle}
            className={BTN}
            data-testid="add-vehicle"
          >
            ＋ 차량 추가{added > 0 ? ` (${added})` : ""}
          </button>
          <span
            role="status"
            aria-label={`알림 ${alerts}건`}
            data-testid="alert-count"
            className={`rounded-full px-2.5 py-1 text-xs font-bold ${
              alerts > 0 ? "bg-orange-500 text-slate-900" : "bg-slate-700 text-slate-300"
            }`}
          >
            🔔 알림 {alerts}
          </span>
          <span
            className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
              connected ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/30 text-red-200"
            }`}
          >
            {connected ? "실시간 연결" : "연결 끊김"}
          </span>
        </div>
      </div>
      {error && (
        <p role="alert" className="bg-red-700 px-4 py-1 text-center text-sm">
          {error}
        </p>
      )}
    </header>
  );
}

import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { api, ApiError, type Estimate, type Vehicle } from "../api";
import { useFeed } from "../feed";
import { hhmm, minutes } from "./format";
import { useMySession } from "./session";
import { anonId } from "./store";
import { Button, CalcBasis, Card, DualSlider } from "./ui";

type EstimateState =
  | { kind: "idle" }
  | { kind: "loading"; last: Estimate | null }
  | { kind: "ok"; est: Estimate }
  | { kind: "error"; message: string };

/** M2. Three taps to finish: CTA on M1, pick a vehicle, register. */
export default function Register() {
  const navigate = useNavigate();
  const { snap } = useFeed();
  const { session, start } = useMySession();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [query, setQuery] = useState("");
  const [vehicleId, setVehicleId] = useState<number | null>(null);
  const [soc, setSoc] = useState<[number, number]>([20, 80]);
  const [chargerId, setChargerId] = useState<number | null>(null); // null = automatic
  const [enterDelay, setEnterDelay] = useState(3);
  const [leaveDelay, setLeaveDelay] = useState(0);
  const [estimate, setEstimate] = useState<EstimateState>({ kind: "idle" });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    api.vehicles().then(setVehicles).catch(() => setVehicles([]));
  }, []);

  // Live estimate from the backend engine, debounced 200 ms; stale requests are aborted.
  useEffect(() => {
    if (vehicleId === null) {
      setEstimate({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setEstimate((prev) => ({
        kind: "loading",
        last: prev.kind === "ok" ? prev.est : prev.kind === "loading" ? prev.last : null,
      }));
      api
        .estimate(
          { vehicle_id: vehicleId, soc_start: soc[0], soc_target: soc[1], charger_id: chargerId },
          ctrl.signal,
        )
        .then((est) => setEstimate({ kind: "ok", est }))
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") return;
          setEstimate({ kind: "error", message: e instanceof ApiError ? e.message : "계산에 실패했습니다." });
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [vehicleId, soc, chargerId]);

  const filtered = useMemo(
    () => vehicles.filter((v) => v.model_name.toLowerCase().includes(query.trim().toLowerCase())),
    [vehicles, query],
  );

  if (session && session.status !== "done") return <Navigate to="/m/queue" replace />;

  const shown = estimate.kind === "ok" ? estimate.est : estimate.kind === "loading" ? estimate.last : null;
  const canSubmit = vehicleId !== null && estimate.kind === "ok" && !submitting;

  const submit = async () => {
    if (vehicleId === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await api.createSession({
        vehicle_id: vehicleId,
        soc_start: soc[0],
        soc_target: soc[1],
        anon_user_id: anonId(),
        charger_id: chargerId,
        enter_delay_min: enterDelay,
        leave_delay_min: leaveDelay,
      });
      start(created.session_id);
      navigate("/m/queue", { replace: true });
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "등록에 실패했습니다.");
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 pb-44">
      <Card>
        <h2 className="mb-2 font-bold">차종</h2>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="차종 검색"
          aria-label="차종 검색"
          className="mb-2 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-base"
        />
        <ul className="grid gap-2" role="radiogroup" aria-label="차종 선택">
          {filtered.map((v) => {
            const on = v.vehicle_id === vehicleId;
            return (
              <li key={v.vehicle_id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setVehicleId(v.vehicle_id)}
                  className={`flex min-h-12 w-full items-center justify-between rounded-xl border px-3 text-left ${
                    on
                      ? "border-emerald-600 bg-emerald-50 font-semibold ring-2 ring-emerald-600"
                      : "border-slate-300 bg-white active:bg-slate-100"
                  }`}
                >
                  <span>{v.model_name}</span>
                  <span className="text-xs text-slate-500">{v.battery_kwh} kWh</span>
                </button>
              </li>
            );
          })}
          {filtered.length === 0 && <li className="py-2 text-sm text-slate-500">검색 결과가 없습니다.</li>}
        </ul>
      </Card>

      <Card>
        <h2 className="mb-1 font-bold">충전량</h2>
        <div className="mb-1 flex justify-between text-center">
          <div>
            <p className="text-xs text-slate-500">현재</p>
            <p className="text-3xl font-bold tabular-nums">{soc[0]}%</p>
          </div>
          <div className="self-center text-slate-400">→</div>
          <div>
            <p className="text-xs text-slate-500">목표</p>
            <p className="text-3xl font-bold tabular-nums">{soc[1]}%</p>
          </div>
        </div>
        <DualSlider low={soc[0]} high={soc[1]} onChange={(l, h) => setSoc([l, h])} />
        <p className="mt-1 text-xs text-slate-500">주황 눈금(80%) 이후에는 충전 속도가 줄어듭니다.</p>
      </Card>

      <Card>
        <h2 className="mb-2 font-bold">충전기</h2>
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="충전기 선택">
          {[{ id: null, label: "자동 배정", sub: "가장 빨리 시작 (추천)" }, ...(snap?.schedule.chargers ?? []).map((c) => ({
            id: c.charger_id as number | null,
            label: `${c.charger_id}번 · ${c.rated_kw} kW`,
            sub: c.status === "fault" ? "점검 중" : `대기 ${c.queue_total}대`,
          }))].map((o) => {
            const on = o.id === chargerId;
            return (
              <button
                key={String(o.id)}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={o.sub === "점검 중"}
                onClick={() => setChargerId(o.id)}
                className={`min-h-14 rounded-xl border px-2 py-1 text-left text-sm disabled:opacity-40 ${
                  on
                    ? "border-emerald-600 bg-emerald-50 font-semibold ring-2 ring-emerald-600"
                    : "border-slate-300 bg-white active:bg-slate-100"
                }`}
              >
                <span className="block">{o.label}</span>
                <span className="block text-xs font-normal text-slate-500">{o.sub}</span>
              </button>
            );
          })}
        </div>
      </Card>

      {shown && estimate.kind !== "error" && <CalcBasis calc={shown.calc} />}

      <details className="rounded-2xl bg-white px-4 py-3 text-sm ring-1 ring-slate-200">
        <summary className="min-h-8 cursor-pointer font-semibold text-slate-600">시연 옵션</summary>
        <label className="mt-2 block">
          <span className="text-slate-600">호출 후 진입까지 걸리는 시간 (가상 운전자)</span>
          <select
            value={enterDelay}
            onChange={(e) => setEnterDelay(Number(e.target.value))}
            className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3"
          >
            <option value={3}>3분 (정상 진입)</option>
            <option value={6}>6분 (노쇼 체험 · 5분 유예 초과)</option>
          </select>
        </label>
        <label className="mt-3 block">
          <span className="text-slate-600">충전 완료 후 차량 이동까지 걸리는 시간 (가상 운전자)</span>
          <select
            value={leaveDelay}
            onChange={(e) => setLeaveDelay(Number(e.target.value))}
            className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3"
          >
            <option value={0}>즉시 이동</option>
            <option value={12}>12분 (방치 체험 · 관제 알림 확인)</option>
          </select>
        </label>
      </details>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-200 bg-white p-3 shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
        <div className="mx-auto max-w-[480px] space-y-2">
          <div aria-live="polite" className="min-h-[3.25rem]">
            {vehicleId === null && (
              <p className="py-2 text-center text-sm text-slate-500">차종을 선택하면 예상 시간이 표시됩니다.</p>
            )}
            {estimate.kind === "error" && (
              <p className="py-2 text-center text-sm font-semibold text-red-700">{estimate.message}</p>
            )}
            {shown && estimate.kind !== "error" && (
              <div className={estimate.kind === "loading" ? "opacity-60" : ""}>
                <p className="text-lg font-bold tabular-nums">
                  예상 {minutes(shown.calc.total_min)} · 종료 {hhmm(shown.expected_end)}{" "}
                  <span className="text-sm font-normal text-slate-600">
                    (범위 {Math.round(shown.calc.low_min)}~{Math.round(shown.calc.high_min)}분)
                  </span>
                </p>
                <p className="text-xs text-slate-500">
                  {shown.charger_id}번 충전기 · 시작 {hhmm(shown.expected_start)}
                </p>
              </div>
            )}
          </div>
          {submitError && <p className="text-sm font-semibold text-red-700">{submitError}</p>}
          <Button onClick={submit} disabled={!canSubmit}>
            {submitting ? "등록 중…" : "대기 등록"}
          </Button>
        </div>
      </div>
    </div>
  );
}

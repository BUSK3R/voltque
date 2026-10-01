import { useState, type ReactNode } from "react";

import { api, type Block, type Snapshot } from "../api";
import { Banner } from "../mobile/ui";
import { hhmm, loadLevel, OVERSTAY_MIN, shortModel } from "./format";

export interface AbandonedCar {
  chargerId: number;
  block: Block;
}

/** A-05: finished cars still plugged in for more than OVERSTAY_MIN minutes. */
export function abandonedCars(snap: Snapshot): AbandonedCar[] {
  return snap.schedule.chargers.flatMap((c) =>
    c.blocks
      .filter((b) => b.kind === "parked" && (b.overstay_min ?? 0) >= OVERSTAY_MIN)
      .map((block) => ({ chargerId: c.charger_id, block })),
  );
}

export function alertCount(snap: Snapshot | null, connected: boolean): number {
  if (!snap) return connected ? 0 : 1;
  const ratio = snap.load.contract_kw > 0 ? snap.load.now_kw / snap.load.contract_kw : 0;
  return (connected ? 0 : 1) + (loadLevel(ratio).alarm ? 1 : 0) + abandonedCars(snap).length;
}

function Row({ car }: { car: AbandonedCar }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const b = car.block;
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.nudge(b.session_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "알림을 보내지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <li
      data-testid={`abandoned-${b.session_id}`}
      className="flex items-center justify-between gap-3 rounded-xl border border-orange-300 bg-orange-50 px-3 py-2 text-sm text-orange-900"
    >
      <span>
        <span className="mr-2 rounded bg-white/70 px-1.5 py-0.5 text-xs font-bold">방치</span>
        충전기 {car.chargerId}번 · #{b.session_id} {shortModel(b.model_name)} — 충전 완료 후{" "}
        <b className="tabular-nums">{(b.overstay_min ?? 0).toFixed(0)}분</b> 경과 (종료{" "}
        {hhmm(b.start)})
        {error && <span className="ml-2 font-semibold text-red-700">{error}</span>}
      </span>
      <button
        type="button"
        onClick={send}
        disabled={busy || b.nudged}
        className="shrink-0 rounded-lg bg-orange-600 px-3 py-1.5 font-semibold text-white hover:bg-orange-700 disabled:bg-slate-300 disabled:text-slate-600"
      >
        {b.nudged ? "알림 전송됨" : "운전자 알림"}
      </button>
    </li>
  );
}

/** Banners that need the operator's attention: load ≥ 90%, abandoned cars, lost connection. */
export default function AlertsPanel({ snap, connected }: { snap: Snapshot | null; connected: boolean }) {
  const items: ReactNode[] = [];
  if (!connected) {
    items.push(
      <Banner key="conn" tone="danger" label="연결 끊김">
        서버와 다시 연결하는 중입니다.
      </Banner>,
    );
  }
  if (snap) {
    const ratio = snap.load.contract_kw > 0 ? snap.load.now_kw / snap.load.contract_kw : 0;
    const level = loadLevel(ratio);
    if (level.alarm) {
      items.push(
        <div key="load" data-testid="load-alert">
          <Banner tone={ratio >= 1 ? "danger" : "warn"} label={ratio >= 1 ? "부하 초과" : "부하 경보"}>
            충전소 부하가 계약전력의 <b className="tabular-nums">{Math.round(ratio * 100)}%</b>입니다.{" "}
            {ratio >= 1
              ? "즉시 출력 제한이 필요합니다."
              : "신규 시작은 출력 제한·시작 지연으로 제어 중입니다."}
          </Banner>
        </div>,
      );
    }
  }
  const cars = snap ? abandonedCars(snap) : [];
  if (items.length === 0 && cars.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="alerts">
      {items}
      {cars.length > 0 && (
        <ul className="space-y-2">
          {cars.map((car) => (
            <Row key={car.block.session_id} car={car} />
          ))}
        </ul>
      )}
    </div>
  );
}

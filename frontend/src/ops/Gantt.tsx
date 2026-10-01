import { useState } from "react";

import type { Block, Charger, Schedule } from "../api";
import { useSimNow } from "../feed";
import { hhmm, kw, OVERSTAY_MIN, shortModel } from "./format";

const LABEL_W = 104;
const PLOT_W = 896;
const W = LABEL_W + PLOT_W;
const AXIS_H = 30;
const ROW_H = 88;
const BLOCK_Y = 12;
const BLOCK_H = ROW_H - 2 * BLOCK_Y;
const HOUR = 3_600_000;
const HALF_SPANS_H = [0.5, 1, 2, 4] as const; // window = now ± this many hours (PRD 5.2: ±2 h default)
const PAN_STEP_MS = 30 * 60_000;

type Palette = { fill: string; text: string; stroke: string };

const CHARGING: Palette = { fill: "#1e3a8a", text: "#ffffff", stroke: "#1e3a8a" };
const WAIT_1: Palette = { fill: "#3b82f6", text: "#ffffff", stroke: "#2563eb" };
const WAIT_2: Palette = { fill: "#bfdbfe", text: "#1e3a8a", stroke: "#93c5fd" };
const PARKED: Palette = { fill: "#e2e8f0", text: "#334155", stroke: "#94a3b8" };
const ORANGE = "#f97316";

function isAbandoned(b: Block): boolean {
  return b.kind === "parked" && (b.overstay_min ?? 0) >= OVERSTAY_MIN;
}

/** Delayed head (load control) or abandoned car: drawn with an orange outline (PRD 5.2). */
function isFlagged(b: Block): boolean {
  return isAbandoned(b) || (b.kind === "waiting" && b.status === "waiting" && b.notice !== null);
}

function paletteOf(b: Block, waitingIndex: number): Palette {
  if (b.kind === "charging") return CHARGING;
  if (b.kind === "parked") return PARKED;
  return waitingIndex === 0 ? WAIT_1 : WAIT_2;
}

function roleLabel(b: Block, waitingIndex: number): string {
  if (b.kind === "charging") return "충전 중";
  if (b.kind === "parked") return isAbandoned(b) ? "방치" : "이동 대기";
  return `대기 ${waitingIndex + 1}`;
}

const CHARGER_STATE: Record<Charger["status"], string> = {
  idle: "비어 있음",
  charging: "충전 중",
  occupied: "차량 이동 대기",
  fault: "점검 중",
};

interface Placed {
  charger: Charger;
  row: number;
  block: Block;
  role: string;
  palette: Palette;
}

function placeBlocks(schedule: Schedule): Placed[] {
  const out: Placed[] = [];
  schedule.chargers.forEach((charger, row) => {
    let waiting = 0;
    for (const block of charger.blocks) {
      const idx = block.kind === "waiting" ? waiting++ : 0;
      out.push({ charger, row, block, role: roleLabel(block, idx), palette: paletteOf(block, idx) });
    }
  });
  return out;
}

function Detail({ placed, onClose }: { placed: Placed; onClose: () => void }) {
  const { block: b, charger: c } = placed;
  return (
    <div
      data-testid="gantt-detail"
      className="mt-3 flex items-start justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(130px,1fr))] gap-x-6 gap-y-1">
        <div>
          <dt className="text-xs text-slate-500">차량</dt>
          <dd className="font-semibold">
            #{b.session_id} {b.model_name}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">충전기 · 상태</dt>
          <dd className="font-semibold">
            {c.charger_id}번 ({c.rated_kw}kW) · {placed.role}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">SoC</dt>
          <dd className="font-semibold tabular-nums">
            {b.kind === "waiting"
              ? `${b.soc_start}% → ${b.soc_target}%`
              : `현재 ${b.soc_current.toFixed(0)}% (목표 ${b.soc_target}%)`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">{b.kind === "waiting" ? "예상 시작 ~ 종료" : "종료 예정"}</dt>
          <dd className="font-semibold tabular-nums">
            {b.kind === "waiting" ? `${hhmm(b.start)} ~ ${hhmm(b.end)}` : hhmm(b.end)}
          </dd>
        </div>
        {b.alloc_kw !== null && (
          <div>
            <dt className="text-xs text-slate-500">출력 제한</dt>
            <dd className="font-semibold tabular-nums">{kw(b.alloc_kw)}</dd>
          </div>
        )}
        {b.overstay_min !== null && (
          <div>
            <dt className="text-xs text-slate-500">완료 후 경과</dt>
            <dd className="font-semibold tabular-nums">{b.overstay_min.toFixed(1)}분</dd>
          </div>
        )}
        {b.notice && (
          <div className="col-span-full text-orange-800">
            <dt className="text-xs text-slate-500">사유</dt>
            <dd className="font-semibold">{b.notice}</dd>
          </div>
        )}
      </dl>
      <button
        type="button"
        onClick={onClose}
        className="shrink-0 rounded-lg px-2 py-1 text-slate-500 ring-1 ring-slate-300 hover:bg-white"
      >
        닫기
      </button>
    </div>
  );
}

/** A-01: one row per charger (current + up to two waiting blocks), centred on the simulation clock. */
export default function Gantt({ schedule }: { schedule: Schedule }) {
  const now = useSimNow();
  const [zoom, setZoom] = useState(2); // index into HALF_SPANS_H
  const [pan, setPan] = useState(0); // ms the window centre is shifted from "now"
  const [selected, setSelected] = useState<number | null>(null);

  const half = HALF_SPANS_H[zoom] * HOUR;
  const left = now + pan - half;
  const xOf = (t: number) => ((t - left) / (2 * half)) * PLOT_W;
  const rows = schedule.chargers.length;
  const H = AXIS_H + rows * ROW_H + 6;

  const step = half <= HOUR ? 15 * 60_000 : half <= 2 * HOUR ? 30 * 60_000 : HOUR;
  const ticks: number[] = [];
  for (let t = Math.ceil(left / step) * step; t <= left + 2 * half; t += step) ticks.push(t);

  const placed = placeBlocks(schedule);
  const current = selected === null ? null : (placed.find((p) => p.block.session_id === selected) ?? null);
  const nowX = xOf(now);

  return (
    <div data-testid="gantt">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-3 w-5 rounded-sm" style={{ background: CHARGING.fill }} />
            충전 중
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-3 w-5 rounded-sm" style={{ background: WAIT_1.fill }} />
            대기 1
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-3 w-5 rounded-sm" style={{ background: WAIT_2.fill }} />
            대기 2
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i
              className="inline-block h-3 w-5 rounded-sm bg-white"
              style={{ border: `3px solid ${ORANGE}` }}
            />
            지연·방치
          </span>
        </div>
        <div className="flex items-center gap-1 text-sm" role="group" aria-label="간트차트 보기 범위">
          <button
            type="button"
            aria-label="30분 이전으로 이동"
            onClick={() => setPan((p) => p - PAN_STEP_MS)}
            className="rounded-lg px-2.5 py-1 ring-1 ring-slate-300 hover:bg-slate-50"
          >
            ◀ 30분
          </button>
          <button
            type="button"
            aria-label="30분 이후로 이동"
            onClick={() => setPan((p) => p + PAN_STEP_MS)}
            className="rounded-lg px-2.5 py-1 ring-1 ring-slate-300 hover:bg-slate-50"
          >
            30분 ▶
          </button>
          <button
            type="button"
            onClick={() => setPan(0)}
            disabled={pan === 0}
            className="rounded-lg px-2.5 py-1 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400"
          >
            지금
          </button>
          <span className="mx-1 text-slate-300">|</span>
          <button
            type="button"
            aria-label="축소"
            disabled={zoom === HALF_SPANS_H.length - 1}
            onClick={() => setZoom((z) => z + 1)}
            className="rounded-lg px-2.5 py-1 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400"
          >
            −
          </button>
          <span className="w-16 text-center tabular-nums text-slate-600" data-testid="gantt-span">
            ±{HALF_SPANS_H[zoom]}시간
          </span>
          <button
            type="button"
            aria-label="확대"
            disabled={zoom === 0}
            onClick={() => setZoom((z) => z - 1)}
            className="rounded-lg px-2.5 py-1 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400"
          >
            +
          </button>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full select-none"
        role="group"
        aria-label="충전기별 스케줄 간트차트"
      >
        {/* charger labels */}
        {schedule.chargers.map((c, i) => (
          <g key={c.charger_id} data-testid={`gantt-row-${c.charger_id}`}>
            <rect
              x={0}
              y={AXIS_H + i * ROW_H}
              width={W}
              height={ROW_H}
              fill={i % 2 === 0 ? "#f8fafc" : "#ffffff"}
            />
            <text x={10} y={AXIS_H + i * ROW_H + 30} fontSize={16} fontWeight={700} fill="#0f172a">
              충전기 {c.charger_id}
            </text>
            <text x={10} y={AXIS_H + i * ROW_H + 48} fontSize={12} fill="#475569">
              {c.rated_kw}kW · {CHARGER_STATE[c.status]}
            </text>
            <text x={10} y={AXIS_H + i * ROW_H + 64} fontSize={12} fill="#475569">
              대기 {c.queue_total}대
            </text>
          </g>
        ))}

        {/* plot area: everything inside is clipped to the time window */}
        <svg x={LABEL_W} y={0} width={PLOT_W} height={H} overflow="hidden">
          {ticks.map((t) => {
            const x = xOf(t);
            return (
              <g key={t}>
                <line x1={x} y1={AXIS_H - 6} x2={x} y2={H} stroke="#e2e8f0" strokeWidth={1} />
                {x > 22 && x < PLOT_W - 22 && (
                  <text x={x} y={AXIS_H - 12} fontSize={12} textAnchor="middle" fill="#475569">
                    {hhmm(t)}
                  </text>
                )}
              </g>
            );
          })}

          {placed.map((p) => {
            const { block: b } = p;
            const x1 = xOf(Date.parse(b.start));
            const x2 = xOf(Date.parse(b.end));
            if (x2 < -4 || x1 > PLOT_W + 4) return null;
            const w = Math.max(6, x2 - x1);
            const y = AXIS_H + p.row * ROW_H + BLOCK_Y;
            const flagged = isFlagged(b);
            const isSel = selected === b.session_id;
            const model = shortModel(b.model_name);
            return (
              <g
                key={b.session_id}
                data-testid={`gantt-block-${b.session_id}`}
                data-kind={b.kind}
                data-flagged={flagged ? "true" : "false"}
                role="button"
                tabIndex={0}
                aria-label={`충전기 ${p.charger.charger_id}번 ${p.role} ${model} ${hhmm(b.start)}에서 ${hhmm(b.end)}`}
                onClick={() => setSelected(isSel ? null : b.session_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(isSel ? null : b.session_id);
                  }
                }}
                style={{
                  transform: `translate(${x1}px, ${y}px)`,
                  transition: "transform 300ms linear",
                  cursor: "pointer",
                  outline: "none",
                }}
              >
                <title>{`#${b.session_id} ${b.model_name} · ${p.role}`}</title>
                <svg
                  x={0}
                  y={0}
                  width={w}
                  height={BLOCK_H}
                  overflow="hidden"
                  style={{ width: w, transition: "width 300ms linear" }}
                >
                  <rect
                    x={1.5}
                    y={1.5}
                    height={BLOCK_H - 3}
                    rx={8}
                    fill={p.palette.fill}
                    stroke={flagged ? ORANGE : isSel ? "#0f172a" : p.palette.stroke}
                    strokeWidth={flagged || isSel ? 3 : 1}
                    strokeDasharray={b.kind === "parked" ? "6 3" : undefined}
                    style={{ width: "calc(100% - 3px)" }}
                  />
                  <text x={10} y={22} fontSize={15} fontWeight={700} fill={p.palette.text}>
                    {model}
                  </text>
                  <text x={10} y={40} fontSize={13} fill={p.palette.text}>
                    {b.kind === "parked"
                      ? `완료 ${hhmm(b.start)} · 이동 예정 ${hhmm(b.end)}`
                      : `${b.kind === "charging" ? `${b.soc_current.toFixed(0)}` : b.soc_start}% → ${b.soc_target}% · 종료 ${hhmm(b.end)}`}
                  </text>
                  <text x={10} y={57} fontSize={12} fontWeight={600} fill={p.palette.text}>
                    {p.role}
                    {b.alloc_kw !== null && b.kind !== "waiting" ? ` · ${kw(b.alloc_kw)}` : ""}
                    {b.kind === "waiting" && b.notice ? " · 시작 지연" : ""}
                  </text>
                </svg>
              </g>
            );
          })}

          {nowX >= 0 && nowX <= PLOT_W && (
            <g data-testid="gantt-now" style={{ pointerEvents: "none" }}>
              <line x1={nowX} y1={AXIS_H - 4} x2={nowX} y2={H} stroke="#dc2626" strokeWidth={2} />
              <rect x={nowX - 26} y={0} width={52} height={16} rx={4} fill="#dc2626" />
              <text x={nowX} y={12} fontSize={11} fontWeight={700} textAnchor="middle" fill="#ffffff">
                {hhmm(now)}
              </text>
            </g>
          )}
        </svg>
      </svg>

      {current && <Detail placed={current} onClose={() => setSelected(null)} />}
    </div>
  );
}

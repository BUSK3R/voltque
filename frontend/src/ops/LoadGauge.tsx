import type { Load } from "../api";
import { kw, loadLevel } from "./format";

const CX = 150;
const CY = 135;
const R = 108;
const STROKE = 22;

/** Point on the semicircle: frac 0 = far left, 1 = far right (the arc runs over the top). */
function point(frac: number, r: number): [number, number] {
  const a = Math.PI * (1 - frac);
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function arc(from: number, to: number): string {
  const [x1, y1] = point(from, R);
  const [x2, y2] = point(to, R);
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

const TICKS = [0.7, 0.9] as const;

/** A-02: half-circle gauge, contract power = full scale, ticks at the 70% / 90% thresholds. */
export default function LoadGauge({ load }: { load: Load }) {
  const ratio = load.contract_kw > 0 ? load.now_kw / load.contract_kw : 0;
  const level = loadLevel(ratio);
  const filled = Math.min(1, Math.max(0, ratio));
  const pct = Math.round(ratio * 100);

  return (
    <div data-testid="load-gauge" data-load-pct={pct}>
      <svg
        viewBox="0 0 300 175"
        className="mx-auto w-full max-w-[260px] min-[1700px]:max-w-[340px]"
        role="meter"
        aria-label="충전소 부하"
        aria-valuemin={0}
        aria-valuemax={load.contract_kw}
        aria-valuenow={Math.round(load.now_kw)}
        aria-valuetext={`${kw(load.now_kw)} / 계약 ${kw(load.contract_kw)} (${pct}%) ${level.label}`}
      >
        <path d={arc(0, 1)} fill="none" stroke="#e2e8f0" strokeWidth={STROKE} strokeLinecap="butt" />
        {filled > 0 && (
          <path
            d={arc(0, filled)}
            fill="none"
            stroke={level.color}
            strokeWidth={STROKE}
            strokeLinecap="butt"
            style={{ transition: "stroke 300ms" }}
          />
        )}
        {TICKS.map((f) => {
          const [x1, y1] = point(f, R - STROKE / 2 - 3);
          const [x2, y2] = point(f, R + STROKE / 2 + 3);
          const [tx, ty] = point(f, R + STROKE / 2 + 14);
          return (
            <g key={f}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#0f172a" strokeWidth={2} />
              <text x={tx} y={ty} fontSize={14} fontWeight={600} textAnchor="middle" fill="#475569">
                {Math.round(f * 100)}%
              </text>
            </g>
          );
        })}
        <text x={CX} y={CY - 38} textAnchor="middle" fontSize={34} fontWeight={700} fill="#0f172a">
          {pct}%
        </text>
        <text x={CX} y={CY - 12} textAnchor="middle" fontSize={18} fontWeight={600} fill="#0f172a">
          {kw(load.now_kw)} / {kw(load.contract_kw)}
        </text>
        <text x={CX} y={CY + 12} textAnchor="middle" fontSize={15} fontWeight={700} fill={level.color}>
          {level.label}
        </text>
        <text x={CX - R} y={CY + 16} textAnchor="middle" fontSize={12} fill="#64748b">
          0
        </text>
        <text x={CX + R} y={CY + 16} textAnchor="middle" fontSize={12} fill="#64748b">
          계약
        </text>
      </svg>
      <p className="text-center text-xs text-slate-500">
        제어 없음이었다면 <b className="tabular-nums text-slate-700">{kw(load.baseline_now_kw)}</b>
        {load.baseline_now_kw > load.now_kw + 0.5 && (
          <> (−{kw(load.baseline_now_kw - load.now_kw)})</>
        )}
      </p>
    </div>
  );
}

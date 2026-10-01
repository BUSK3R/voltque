import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Load } from "../api";
import { hhmm } from "./format";

const MAX_POINTS = 180; // newest 3 hours at one point per simulated minute

interface Row {
  t: number;
  base: number;
  ctrl: number;
  /** reduction = what VoltQueue shaved off; stacked on `ctrl` it fills the band up to the baseline */
  cut: number;
}

function rowsOf(load: Load): Row[] {
  const n = Math.min(load.controlled.length, load.baseline.length);
  const rows: Row[] = [];
  for (let i = Math.max(0, n - MAX_POINTS); i < n; i++) {
    const base = load.baseline[i].kw;
    const ctrl = load.controlled[i].kw;
    rows.push({ t: Date.parse(load.controlled[i].ts), base, ctrl, cut: Math.max(0, base - ctrl) });
  }
  return rows;
}

function Swatch({
  children,
  line,
}: {
  children: string;
  line: "dash" | "solid" | "area" | "limit" | "contract";
}) {
  const mark =
    line === "area" ? (
      <span className="inline-block h-3 w-5 rounded-sm bg-orange-400/40 ring-1 ring-orange-400" />
    ) : (
      <svg width="24" height="8" aria-hidden>
        <line
          x1="0"
          y1="4"
          x2="24"
          y2="4"
          stroke={
            line === "solid" ? "#2563eb" : line === "limit" || line === "contract" ? "#dc2626" : "#475569"
          }
          strokeWidth={line === "solid" ? 3 : 2}
          strokeDasharray={line === "dash" ? "5 4" : line === "limit" ? "2 3" : undefined}
        />
      </svg>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
      {mark}
      {children}
    </span>
  );
}

/** A-04: "no control" (dashed) vs "VoltQueue" (solid) with the contract line and the reduced area. */
export default function LoadChart({ load }: { load: Load }) {
  const rows = rowsOf(load);
  const peak = rows.reduce((m, r) => Math.max(m, r.base, r.ctrl), 0);
  const yMax = Math.ceil(Math.max(load.contract_kw * 1.15, peak * 1.05) / 100) * 100;

  return (
    <div data-testid="load-chart">
      <div className="mb-1 flex flex-wrap gap-x-4 gap-y-1">
        <Swatch line="dash">제어 없음</Swatch>
        <Swatch line="solid">VoltQueue 적용</Swatch>
        <Swatch line="area">피크 감소</Swatch>
        <Swatch line="contract">계약전력</Swatch>
        <Swatch line="limit">제어 한도(90%)</Swatch>
      </div>
      <div className="h-[112px] min-[1700px]:h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="t"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => hhmm(v)}
              tick={{ fontSize: 11, fill: "#64748b" }}
              minTickGap={32}
            />
            <YAxis
              domain={[0, yMax]}
              tick={{ fontSize: 11, fill: "#64748b" }}
              width={40}
              unit=""
            />
            <Tooltip
              labelFormatter={(l) => hhmm(Number(l))}
              formatter={(v, name) => [`${Math.round(Number(v))} kW`, String(name)]}
            />
            <Area
              dataKey="ctrl"
              stackId="band"
              stroke="none"
              fill="none"
              isAnimationActive={false}
              legendType="none"
              name="적용(기준)"
              tooltipType="none"
            />
            <Area
              dataKey="cut"
              stackId="band"
              stroke="none"
              fill="#fb923c"
              fillOpacity={0.35}
              isAnimationActive={false}
              name="피크 감소"
            />
            <Line
              dataKey="base"
              name="제어 없음"
              stroke="#475569"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="ctrl"
              name="VoltQueue 적용"
              stroke="#2563eb"
              strokeWidth={3}
              dot={false}
              isAnimationActive={false}
            />
            <ReferenceLine
              y={load.contract_kw}
              stroke="#dc2626"
              strokeWidth={2}
              label={{
                value: `계약 ${Math.round(load.contract_kw)}kW`,
                position: "insideTopLeft",
                fill: "#b91c1c",
                fontSize: 11,
              }}
            />
            <ReferenceLine
              y={load.limit_kw}
              stroke="#dc2626"
              strokeDasharray="2 4"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

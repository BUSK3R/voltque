import { useEffect, useState } from "react";

import { api, type Kpi, type KpiDay } from "../api";

function Sparkline({ values }: { values: number[] }) {
  const w = 120;
  const h = 32;
  if (values.length < 2) return <svg width={w} height={h} aria-hidden />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (w - 6) + 3;
    const y = h - 4 - ((v - min) / span) * (h - 8);
    return [x, y] as const;
  });
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline
        points={pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
        fill="none"
        stroke="#64748b"
        strokeWidth={1.5}
      />
      <circle cx={last[0]} cy={last[1]} r={3} fill="#2563eb" />
    </svg>
  );
}

interface CardSpec {
  id: string;
  title: string;
  value: string;
  unit: string;
  sub: string;
  today: number;
  yesterday: number | null;
  /** which direction is an improvement */
  better: "up" | "down";
  digits: number;
  spark: number[];
  /** nothing measured yet: a day-over-day arrow would only compare against a partial day */
  collecting: boolean;
}

function Delta({ spec }: { spec: CardSpec }) {
  if (spec.yesterday === null) return <span className="text-xs text-slate-400">전일 데이터 없음</span>;
  if (spec.collecting) {
    return (
      <span className="text-xs text-slate-500">
        집계 중 · 전일 {spec.yesterday.toFixed(spec.digits)}
        {spec.unit}
      </span>
    );
  }
  const diff = spec.today - spec.yesterday;
  const eps = 0.5 * 10 ** -spec.digits;
  if (Math.abs(diff) < eps) return <span className="text-xs text-slate-500">전일 대비 ― 동일</span>;
  const up = diff > 0;
  const good = up === (spec.better === "up");
  // direction arrow + signed number + word: never colour alone
  return (
    <span
      className={`text-xs font-semibold tabular-nums ${good ? "text-emerald-700" : "text-red-700"}`}
    >
      전일 대비 {up ? "▲" : "▼"} {up ? "+" : "−"}
      {Math.abs(diff).toFixed(spec.digits)}
      {spec.unit} ({good ? "개선" : "악화"})
    </span>
  );
}

function Card({ spec }: { spec: CardSpec }) {
  return (
    <section
      data-testid={`kpi-${spec.id}`}
      className="rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200"
    >
      <h3 className="text-sm font-semibold text-slate-600">{spec.title}</h3>
      <div className="mt-1 flex items-end justify-between gap-2">
        <p className="text-4xl font-bold tabular-nums tracking-tight" data-testid={`kpi-${spec.id}-value`}>
          {spec.value}
          <span className="ml-1 text-lg font-semibold text-slate-500">{spec.unit}</span>
        </p>
        <Sparkline values={spec.spark} />
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <Delta spec={spec} />
        <span className="truncate text-xs text-slate-500">{spec.sub}</span>
      </div>
    </section>
  );
}

/** A-03 / PRD 5.3: four KPI cards with a day-over-day arrow and a 7-day sparkline ending at "now". */
export default function KpiCards({ kpi, chargers }: { kpi: Kpi; chargers: number }) {
  const [history, setHistory] = useState<KpiDay[]>([]);
  useEffect(() => {
    api
      .kpiHistory()
      .then(setHistory)
      .catch(() => setHistory([]));
  }, []);
  const prev = history.length > 0 ? history[history.length - 1] : null;
  const series = (pick: (d: KpiDay) => number, now: number) => [...history.map(pick), now];

  const specs: CardSpec[] = [
    {
      id: "turnover",
      title: "일일 회전수",
      value: String(kpi.sessions_done),
      unit: "대",
      sub: `충전기당 평균 ${(chargers > 0 ? kpi.sessions_done / chargers : 0).toFixed(1)}대`,
      today: kpi.sessions_done,
      yesterday: prev?.sessions ?? null,
      better: "up",
      digits: 0,
      spark: series((d) => d.sessions, kpi.sessions_done),
      collecting: kpi.sessions_done === 0,
    },
    {
      id: "wait",
      title: "평균 대기시간",
      value: kpi.avg_wait_min.toFixed(1),
      unit: "분",
      sub: "등록 → 충전 시작",
      today: kpi.avg_wait_min,
      yesterday: prev?.avg_wait_min ?? null,
      better: "down",
      digits: 1,
      spark: series((d) => d.avg_wait_min, kpi.avg_wait_min),
      collecting: kpi.sessions_done === 0 && kpi.avg_wait_min === 0,
    },
    {
      id: "efficiency",
      title: "전력 사용 효율",
      value: (kpi.load_factor * 100).toFixed(0),
      unit: "%",
      sub: "부하율 = 평균 ÷ 최대 부하",
      today: kpi.load_factor * 100,
      yesterday: prev ? prev.load_factor * 100 : null,
      better: "up",
      digits: 0,
      spark: series((d) => d.load_factor * 100, kpi.load_factor * 100),
      collecting: kpi.peak_kw === 0,
    },
    {
      id: "peak",
      title: "피크 경감량",
      value: kpi.peak_reduction_kw.toFixed(0),
      unit: "kW",
      sub: `제어 없음 ${kpi.baseline_peak_kw.toFixed(0)} → 적용 ${kpi.peak_kw.toFixed(0)} kW`,
      today: kpi.peak_reduction_kw,
      yesterday: prev?.peak_reduction_kw ?? null,
      better: "up",
      digits: 0,
      spark: series((d) => d.peak_reduction_kw, kpi.peak_reduction_kw),
      collecting: kpi.peak_kw === 0,
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {specs.map((s) => (
        <Card key={s.id} spec={s} />
      ))}
    </div>
  );
}

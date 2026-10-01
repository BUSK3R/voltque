import { useState, type ReactNode } from "react";

import type { Calc } from "../api";
import { kw, minutes } from "./format";

/* Status colours always come with a text label (PRD 5: never colour alone). */
type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

const TONE: Record<Tone, string> = {
  ok: "bg-emerald-50 text-emerald-800 border-emerald-300",
  warn: "bg-orange-50 text-orange-800 border-orange-300",
  danger: "bg-red-50 text-red-800 border-red-300",
  info: "bg-sky-50 text-sky-800 border-sky-300",
  neutral: "bg-slate-100 text-slate-700 border-slate-300",
};

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

export function Banner({
  tone,
  label,
  children,
}: {
  tone: Tone;
  label: string;
  children: ReactNode;
}) {
  return (
    <div role="status" className={`rounded-xl border px-3 py-2.5 text-sm ${TONE[tone]}`}>
      <span className="mr-2 rounded bg-white/70 px-1.5 py-0.5 text-xs font-bold">{label}</span>
      {children}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 ${className}`}>
      {children}
    </section>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger";
  type?: "button" | "submit";
}) {
  const style = {
    primary: "bg-emerald-600 text-white active:bg-emerald-700 disabled:bg-slate-300",
    secondary: "bg-white text-slate-800 ring-1 ring-slate-300 active:bg-slate-100",
    danger: "bg-white text-red-700 ring-1 ring-red-300 active:bg-red-50",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`min-h-12 w-full rounded-xl px-4 text-base font-semibold disabled:cursor-not-allowed ${style}`}
    >
      {children}
    </button>
  );
}

/** Two-step confirmation that does not use window.confirm. */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button variant="danger" onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      <Button variant="secondary" onClick={() => setAsking(false)}>
        돌아가기
      </Button>
      <Button variant="danger" onClick={onConfirm}>
        {confirmLabel}
      </Button>
    </div>
  );
}

/** Current / target SoC on one track. The tick marks the 80% tapering point. */
export function DualSlider({
  low,
  high,
  onChange,
}: {
  low: number;
  high: number;
  onChange: (low: number, high: number) => void;
}) {
  return (
    <div className="relative h-11 select-none">
      <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-slate-200" />
      <div
        className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-emerald-500"
        style={{ left: `${low}%`, width: `${high - low}%` }}
      />
      <div
        className="absolute top-1/2 h-5 w-0.5 -translate-y-1/2 bg-orange-500"
        style={{ left: "80%" }}
        aria-hidden
      />
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={low}
        aria-label="현재 충전량(%)"
        className="dual-range"
        style={{ zIndex: low > 50 ? 4 : 2 }}
        onChange={(e) => onChange(Math.min(Number(e.target.value), high - 1), high)}
      />
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={high}
        aria-label="목표 충전량(%)"
        className="dual-range"
        style={{ zIndex: 3 }}
        onChange={(e) => onChange(low, Math.max(Number(e.target.value), low + 1))}
      />
    </div>
  );
}

export function BatteryGauge({ soc, target }: { soc: number; target: number }) {
  return (
    <div className="relative flex items-end gap-3">
      <div className="relative">
        <div className="mx-auto h-2 w-8 rounded-t bg-slate-700" />
        <div
          role="img"
          aria-label={`배터리 ${Math.round(soc)}%, 목표 ${target}%`}
          className="relative h-60 w-28 overflow-hidden rounded-2xl border-4 border-slate-700 bg-white"
        >
          <div
            className="absolute inset-x-0 bottom-0 bg-emerald-500 transition-[height] duration-500"
            style={{ height: `${soc}%` }}
          />
          <div
            className="absolute inset-x-0 border-t-2 border-dashed border-orange-500"
            style={{ bottom: "80%" }}
          />
          <div
            className="absolute inset-x-0 border-t-2 border-slate-800"
            style={{ bottom: `${target}%` }}
          />
          <div className="absolute inset-0 flex items-center justify-center text-3xl font-bold text-slate-900 mix-blend-multiply">
            {Math.round(soc)}%
          </div>
        </div>
      </div>
      <div className="relative h-60 text-xs font-semibold">
        <span className="absolute left-0 whitespace-nowrap text-orange-700" style={{ bottom: "calc(80% - 8px)" }}>
          ◀ 80% 감속
        </span>
        <span
          className="absolute left-0 whitespace-nowrap text-slate-800"
          style={{ bottom: `calc(${target}% - 8px)`, marginTop: 0 }}
        >
          {target !== 80 ? `◀ 목표 ${target}%` : ""}
        </span>
      </div>
    </div>
  );
}

/** "계산 근거 보기": inputs, formula and per-segment time (PRD 4.4 explainability). */
export function CalcBasis({ calc }: { calc: Calc }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="min-h-11 w-full rounded-xl bg-slate-100 px-4 text-sm font-semibold text-slate-700 active:bg-slate-200"
      >
        계산 근거 {open ? "접기 ▲" : "보기 ▼"}
      </button>
      {open && (
        <div className="mt-2 space-y-2 rounded-xl bg-slate-50 p-3 text-sm ring-1 ring-slate-200">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-slate-500">충전기 출력</dt>
            <dd className="text-right font-medium">{kw(calc.charger_kw)}</dd>
            <dt className="text-slate-500">유효 출력 P_eff</dt>
            <dd className="text-right font-medium">{kw(calc.p_eff_kw)}</dd>
          </dl>
          <ul className="divide-y divide-slate-200 rounded-lg bg-white ring-1 ring-slate-200">
            {calc.segments.map((s) => (
              <li key={s.name} className="flex justify-between px-3 py-2">
                <span>
                  {s.soc_from.toFixed(0)}→{s.soc_to.toFixed(0)}%{" "}
                  <span className="text-slate-500">
                    ({s.name === "taper" ? "속도 감소 구간" : "일정 출력 구간"})
                  </span>
                </span>
                <span className="font-semibold">{s.minutes.toFixed(1)}분</span>
              </li>
            ))}
            <li className="flex justify-between px-3 py-2 font-bold">
              <span>합계</span>
              <span>
                {calc.total_min.toFixed(1)}분{" "}
                <span className="font-normal text-slate-500">
                  ({minutes(calc.low_min)}~{minutes(calc.high_min)})
                </span>
              </span>
            </li>
          </ul>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-800 p-3 text-xs leading-relaxed text-slate-100">
{`P_eff = min(Pc, Pv) × η
T1 = C × (min(s1, 80) − s0) / (100 × P_eff)
T2 = C × 20 / (100 × α × P_eff) × ln(k(a)/k(s1))
총 시간 = γ × (T1 + T2),  범위 = 0.92T ~ 1.10T`}
          </pre>
          <p className="text-xs text-slate-500">
            차종·충전기 수치는 시연용 예시값이며 실제 제원이 아닙니다.
          </p>
        </div>
      )}
    </div>
  );
}

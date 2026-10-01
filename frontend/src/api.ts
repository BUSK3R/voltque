/** Typed client for the backend (always via the /api proxy; no mocking). */

export interface Vehicle {
  vehicle_id: number;
  model_name: string;
  battery_kwh: number;
  max_dc_kw: number;
}

export interface Segment {
  name: string;
  soc_from: number;
  soc_to: number;
  minutes: number;
}

export interface Calc {
  total_min: number;
  low_min: number;
  high_min: number;
  t1_min: number;
  t2_min: number;
  p_eff_kw: number;
  charger_kw: number;
  segments: Segment[];
}

export interface Estimate {
  charger_id: number;
  calc: Calc;
  expected_start: string;
  expected_end: string;
}

export type SessionStatus = "waiting" | "called" | "charging" | "done" | "cancelled" | "no_show";

export interface LaneBlock {
  session_id: number;
  kind: string;
  status: string;
  start: string;
  end: string;
  is_me: boolean;
}

export interface Session {
  session_id: number;
  status: SessionStatus;
  charger_id: number;
  vehicle_id: number;
  model_name: string;
  soc_start: number;
  soc_target: number;
  soc_current: number;
  battery_kwh: number;
  charged_kwh: number;
  current_kw: number;
  queue_pos: number | null;
  ahead: number;
  planned_start: string | null;
  planned_end: string | null;
  alloc_kw: number | null;
  notice: string | null;
  resume_at: string | null;
  called_at: string | null;
  no_show_at: string | null;
  no_show_count: number;
  actual_start: string | null;
  actual_end: string | null;
  lane: LaneBlock[];
  calc: Calc;
}

export interface Block {
  session_id: number;
  kind: string;
  status: string;
  start: string;
  end: string;
  queue_pos: number | null;
  model_name: string;
  soc_start: number;
  soc_target: number;
  soc_current: number;
  alloc_kw: number | null;
  notice: string | null;
}

export interface Charger {
  charger_id: number;
  rated_kw: number;
  connector_type: string;
  status: string;
  queue_total: number;
  free_at: string;
  blocks: Block[];
}

export interface Schedule {
  station_id: number;
  station_name: string;
  now: string;
  running: boolean;
  speed: number;
  contract_kw: number;
  limit_kw: number;
  chargers: Charger[];
}

export interface Load {
  station_id: number;
  now: string;
  contract_kw: number;
  limit_kw: number;
  now_kw: number;
  baseline_now_kw: number;
}

export interface SimState {
  running: boolean;
  speed: number;
  scenario: string | null;
  now: string;
  elapsed_min: number;
}

export interface Snapshot {
  type: "snapshot";
  reason: string;
  sim: SimState;
  schedule: Schedule;
  load: Load;
}

export interface NewSession {
  vehicle_id: number;
  soc_start: number;
  soc_target: number;
  anon_user_id: string;
  charger_id: number | null;
  enter_delay_min: number;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface ErrorBody {
  detail?: string | { msg?: string }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = (await res.json()) as ErrorBody;
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d) => d.msg ?? "").join(", ");
    } catch {
      // keep the status text
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  vehicles: () => request<Vehicle[]>("/vehicles"),
  estimate: (
    body: { vehicle_id: number; soc_start: number; soc_target: number; charger_id: number | null },
    signal?: AbortSignal,
  ) => request<Estimate>("/estimate", { ...post(body), signal }),
  createSession: (body: NewSession) => request<Session>("/sessions", post(body)),
  session: (id: number) => request<Session>(`/sessions/${id}`),
  cancel: (id: number) => request<Session>(`/sessions/${id}/cancel`, { method: "POST" }),
};

export const STATION_ID = 1;

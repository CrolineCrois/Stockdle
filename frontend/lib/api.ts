/** Typed client for the TAPE backend. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

export const CURVE_LEN = 50;
export const VISIBLE_LEN = 75;
export const ROUND_SECONDS = 10;

export type RoundType = 'electricity' | 'stock' | 'trends';

export interface RoundContext {
  kind: RoundType;
  eyebrow: string;
  title: string;
  subtitle: string;
  chips: string[];
  headline?: string | null;
  publisher?: string | null;
}

export interface RoundScale {
  y_min: number;
  y_max: number;
  unit: string;
  y_label: string;
}

export interface AxisTick {
  /** Canvas index, 0..VISIBLE_LEN + CURVE_LEN - 1. */
  i: number;
  label: string;
  /** A new day / year: always drawn, with a full-height gridline. */
  major: boolean;
}

export interface RoundXAxis {
  ticks: AxisTick[];
  /** Inclusive canvas-index ranges to shade (night, on grid rounds). */
  bands: Array<[number, number]>;
  /** Local time at the cut, shown beside NOW. */
  now: string;
  note: string | null;
}

export interface GameRound {
  id: string;
  type: RoundType;
  source_key: string;
  visible: number[];
  context: RoundContext;
  scale: RoundScale;
  x_label: string;
  /** Absent on rounds built before local-time axes existed. */
  x_axis?: RoundXAxis;
  is_seed: boolean;
}

export interface NextRound {
  round: GameRound | null;
  mode: 'daily' | 'endless';
  index: number;
  of: number;
  done: boolean;
  daily_number: number | null;
}

export interface Bonus {
  key: string;
  label: string;
  points: number;
}

export interface ScoreBreakdown {
  base: number;
  total: number;
  rmse: number;
  sigma: number;
  err: number;
  multiplier: number;
  streak_before: number;
  streak_after: number;
  bullseye: boolean;
  bonuses: Bonus[];
  bonus_points: number;
  ai_rmse: number | null;
  crowd_rmse: number | null;
  turning_point: { kind: 'max' | 'min'; index: number; hit: boolean } | null;
}

export interface RevealInfo {
  ticker?: string;
  name?: string;
  date?: string;
  region?: string;
  city?: string;
  term?: string;
  cut_at?: string;
  headline?: string | null;
  publisher?: string | null;
  forecast_high_f?: number | null;
  geo?: string;
}

export interface SubmitResult {
  round_id: string;
  truth: number[];
  ai_curve: number[];
  crowd_curve: number[] | null;
  crowd_n: number;
  score_breakdown: ScoreBreakdown;
  reveal_info: RevealInfo;
  streak: number;
  ai_version: number;
  player_total: number;
}

export interface PlayerInfo {
  player_id: string;
  name: string;
  rounds_played: number;
  total_score: number;
  streak: number;
  best_streak: number;
}

export interface LeaderRow {
  rank: number;
  name: string;
  player_id: string;
  score: number;
  rounds: number;
  best_streak: number;
  avg: number;
  is_bot: boolean;
}

export interface AIVersion {
  version: number;
  created_at: string | null;
  drawings_seen: number;
  new_drawings: number;
  weights: Record<string, number>;
  rmse_model: number | null;
  rmse_crowd: number | null;
  rmse_blend: number | null;
  n_eval: number;
  note: string;
}

export interface DashboardData {
  versions: Array<{
    version: number;
    created_at: string | null;
    drawings_seen: number;
    model: number | null;
    crowd: number | null;
    blend: number | null;
    n_eval: number;
    weights: Record<string, number>;
    note: string;
  }>;
  improvement: Array<{ bucket: string; avg_score: number; n: number }>;
  bias: Array<{ type: string; avg_signed_error: number; avg_abs_error: number; n: number }>;
  totals: {
    drawings: number;
    players: number;
    rounds: number;
    ai_version: number;
    beat_ai_rate: number;
    avg_score: number;
    bullseyes: number;
    weights: Record<string, number>;
    rounds_with_crowd: number;
    retrain_every: number;
    next_retrain_in: number;
    latest_note: string;
  };
}

export interface DailySummary {
  number: number;
  complete: boolean;
  scores: number[];
  beat_ai: number;
  total: number;
  share: string;
}

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    cache: 'no-store',
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ ok: boolean; rounds: number; drawings: number }>('/api/health'),

  upsertPlayer: (name: string, playerId?: string | null) =>
    request<PlayerInfo>('/api/player', {
      method: 'POST',
      body: JSON.stringify({ name, player_id: playerId ?? null }),
    }),

  nextRound: (mode: 'daily' | 'endless', playerId: string) =>
    request<NextRound>(
      `/api/round/next?mode=${mode}&player_id=${encodeURIComponent(playerId)}`,
    ),

  submit: (
    roundId: string,
    body: { player_id: string; curve: number[]; time_ms: number; mode: string; skipped?: boolean },
  ) =>
    request<SubmitResult>(`/api/round/${roundId}/submit`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  daily: () =>
    request<{ number: number; date: string; round_ids: string[]; count: number }>('/api/daily'),

  dailySummary: (playerId: string) =>
    request<DailySummary>(`/api/player/${encodeURIComponent(playerId)}/daily`),

  leaderboard: (period: 'today' | 'all') =>
    request<{ period: string; rows: LeaderRow[] }>(`/api/leaderboard?period=${period}`),

  aiVersion: () => request<AIVersion>('/api/ai/version'),

  dashboard: () => request<DashboardData>('/api/dashboard'),

  forceRetrain: (token: string) =>
    request<{ queued: boolean; current_version: number }>('/api/admin/retrain', {
      method: 'POST',
      headers: { 'x-admin-token': token },
    }),
};

export { ApiError };

/** Map a normalised 0-1 value back to the round's real units. */
export function toReal(value: number, scale: RoundScale): number {
  return scale.y_min + value * (scale.y_max - scale.y_min);
}

export function formatReal(value: number, scale: RoundScale): string {
  const real = toReal(value, scale);
  const span = Math.abs(scale.y_max - scale.y_min);
  if (scale.unit === '$') {
    return `$${real.toFixed(span < 5 ? 2 : 1)}`;
  }
  if (scale.unit === 'MW') {
    return real >= 10000 ? `${(real / 1000).toFixed(1)}k` : Math.round(real).toLocaleString();
  }
  return span < 10 ? real.toFixed(1) : Math.round(real).toString();
}

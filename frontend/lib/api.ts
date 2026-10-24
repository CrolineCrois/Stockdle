/** Typed client for the Sneak It Past backend. */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

export interface PlayerInfo {
  player_id: string;
  name: string;
  runs: number;
  best_score: number;
}

export interface RunInfo {
  id: string;
  lives: number;
  max_lives: number;
  streak: number;
  best_streak: number;
  score: number;
  snuck: number;
  caught: number;
  rounds_played: number;
  over: boolean;
  detector_version: string;
}

export interface HeadlineInfo {
  id: number;
  text: string;
  snippet: string;
  source: string;
  url: string;
  published_at: string | null;
}

export interface RoundInfo {
  id: string;
  status: 'active' | 'snuck' | 'caught' | 'timeout' | 'exhausted';
  is_bounty: boolean;
  timer_start_s: number;
  remaining_s: number;
  attempts_used: number;
  max_attempts: number;
  headline: HeadlineInfo;
}

export interface Rules {
  max_words: number;
  threshold: number;
  near_miss_from: number;
  max_attempts: number;
  lives: number;
}

export interface GameState {
  run: RunInfo;
  round: RoundInfo | null;
  rules: Rules;
}

export interface WordChange {
  op: 'replace' | 'insert' | 'delete';
  before: string;
  after: string;
  count: number;
}

export interface MeterReading {
  suspicion: number;
  num_changes: number;
  changes: WordChange[];
  over_limit: boolean;
  remaining_s: number;
}

export interface Verdict {
  is_false: boolean;
  is_plausible: boolean;
  is_grammatical: boolean;
  edit_type: string;
  explanation: string;
  judge: string;
}

export interface Points {
  base: number;
  word_mult: number;
  streak_mult: number;
  time_mult: number;
  novelty_mult: number;
  bounty_mult: number;
  total: number;
  quick_hands: boolean;
}

export type Outcome = 'snuck' | 'caught' | 'invalid' | 'timeout';

export interface SubmitResult {
  outcome: Outcome;
  suspicion: number | null;
  points: Points | null;
  /** Empty for a timeout: nothing was judged. */
  verdict: Partial<Verdict>;
  changes: WordChange[];
  num_changes: number;
  near_miss: boolean;
  events: string[];
  round_over: boolean;
  run_over: boolean;
  attempts_used: number;
  remaining_s: number;
  state: GameState;
}

export interface TracePoint {
  t_ms: number;
  s: number;
  text?: string;
}

export interface LeaderRow {
  rank: number;
  name: string;
  score: number;
  snuck: number;
  best_streak: number;
  detector_version: string;
}

export class ApiError extends Error {
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

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const api = {
  health: () =>
    request<{ ok: boolean; detector: string | null; judge: string; headlines: number }>(
      '/api/health',
    ),

  upsertPlayer: (name: string, playerId?: string | null) =>
    post<PlayerInfo>('/api/player', { name, player_id: playerId ?? null }),

  startRun: (playerId: string) => post<GameState>('/api/run', { player_id: playerId }),

  nextRound: (runId: string, playerId: string) =>
    post<GameState>(`/api/run/${runId}/next`, { player_id: playerId }),

  meter: (roundId: string, playerId: string, edited: string) =>
    post<MeterReading>(`/api/round/${roundId}/suspicion`, { player_id: playerId, edited }),

  submit: (roundId: string, playerId: string, edited: string, trace: TracePoint[], ms: number) =>
    post<SubmitResult>(`/api/round/${roundId}/submit`, {
      player_id: playerId,
      edited,
      trace,
      time_to_submit_ms: ms,
    }),

  timeout: (roundId: string, playerId: string, edited: string, trace: TracePoint[], ms: number) =>
    post<SubmitResult>(`/api/round/${roundId}/timeout`, {
      player_id: playerId,
      edited,
      trace,
      time_to_submit_ms: ms,
    }),

  leaderboard: () => request<{ rows: LeaderRow[] }>('/api/leaderboard'),
};

export interface ExploitRow {
  id: number;
  player: string;
  original: string;
  edited: string;
  /** Always shown beside the edited text: these are player-made fakes. */
  label: string;
  edit_type: string;
  changes: WordChange[];
  points: number;
  suspicion: number | null;
  novelty_distance: number | null;
  detector_version: string;
  patched_in: string | null;
  created_at: string;
}

export const exploitsApi = {
  list: (limit = 20) => request<{ label: string; rows: ExploitRow[] }>(`/api/exploits?limit=${limit}`),
};

export interface PatchNotice {
  id: number;
  patched_in: string;
  original: string;
  changes: WordChange[];
  label: string;
}

export const noticesApi = {
  /** Exploits of yours caught by a later patch day. Each is returned once. */
  list: (playerId: string) =>
    request<{ notices: PatchNotice[] }>(`/api/player/${encodeURIComponent(playerId)}/notices`),
};

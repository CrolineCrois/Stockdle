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
  partial: number;
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
  status: 'active' | 'snuck' | 'partial' | 'caught' | 'timeout' | 'exhausted';
  is_bounty: boolean;
  /** "evidence": the source is in the verifier's index; "breaking": it isn't. */
  mode: 'evidence' | 'breaking';
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

/** The judge's two-run ruling. */
export interface Verdict {
  valid: boolean;
  reason: string;
  materiality: number;
  specificity: number;
  original_specificity: number;
  vagueness_flags: string[];
  edit_type: string;
  explanation: string;
  judge: string;
  runs: unknown[];
}

export interface EvidencePassage {
  text: string;
  source: string;
  url: string;
  headline: string;
  probs: { supported: number; refuted: number; nei: number };
  decisive: boolean;
}

export interface VerifierResult {
  verdict: 'supported' | 'refuted' | 'nei';
  probs: { supported: number; refuted: number; nei: number };
  version: string;
  evidence: EvidencePassage[];
}

export interface Points {
  base: number;
  word_mult: number;
  streak_mult: number;
  time_mult: number;
  novelty_mult: number;
  bounty_mult: number;
  materiality_mult: number;
  sharp_mult: number;
  vague_mult: number;
  partial_mult: number;
  total: number;
  quick_hands: boolean;
}

export type Outcome = 'snuck' | 'partial' | 'caught' | 'invalid' | 'timeout';

export interface SubmitResult {
  outcome: Outcome;
  suspicion: number | null;
  points: Points | null;
  /** Empty for a timeout: nothing was judged. */
  verdict: Partial<Verdict>;
  verifier: VerifierResult | null;
  mode: 'evidence' | 'breaking';
  tags: string[];
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

export interface VersionRow {
  name: string;
  kind: string;
  note: string;
  n_train: number;
  is_current: boolean;
  created_at: string;
  n_human: number;
  n_machine: number;
  n_true: number;
  human_catch: number | null;
  machine_catch: number | null;
  false_alarm: number | null;
  error?: string;
}

export interface Analytics {
  judge_filter: 'all' | 'real';
  mock_judged_attempts: number;
  totals: {
    rounds_played: number;
    attempts: number;
    exploits: number;
    patched: number;
    zero_days: number;
    players: number;
    current_detector: string;
  };
  versions: VersionRow[];
  edit_types: { edit_type: string; count: number }[];
  words_added: { word: string; count: number }[];
  words_removed: { word: string; count: number }[];
  timer: { bucket: string; n: number; success_rate: number | null; avg_suspicion: number | null }[];
  outcomes: Record<string, number>;
  threshold: number;
  verifier_failures: { edit_type: string; n: number; failure_rate: CI; supported: number; nei: number }[];
  modes: { mode: string; n: number; snuck: number; partial: number; win_rate: number | null }[];
  review: ReviewStats;
  progress: ({ day: string; total: number } & Record<string, number | string>)[];
  evaluation: EvalResults | null;
}

export interface CI {
  value: number | null;
  lo: number | null;
  hi: number | null;
  n: number;
}

export interface ModelScores {
  held_out_exploits: { overall: CI; by_edit_type: Record<string, CI> };
  fresh_exploits: { overall: CI; by_edit_type: Record<string, CI> };
  true_headlines: { overall: CI };
  vitaminc: { accuracy: CI; macro_f1: CI };
}

export interface EvalResults {
  created_at: string;
  dev_data: boolean;
  base_model: string;
  counts: Record<string, number>;
  synthetic_provider: string | null;
  models: Record<string, ModelScores>;
}

export const analyticsApi = {
  get: (judge: 'all' | 'real') => request<Analytics>(`/api/analytics?judge=${judge}`),
};

export interface ReviewItem {
  id: number;
  created_at: string;
  outcome: 'snuck' | 'partial';
  mode: 'evidence' | 'breaking';
  original: string;
  edited: string;
  changes: WordChange[];
  edit_type: string;
  materiality: number | null;
  specificity: number | null;
  original_specificity: number | null;
  vagueness_flags: string[];
  judge: string;
  judge_runs: { phrasing: string; is_false: boolean; materiality: number; specificity: number; explanation: string }[];
  verifier: { verdict: string; version: string; probs: Record<string, number> };
  evidence: { text: string; source: string; same_story: boolean }[];
  review_status: string;
  reviewer_id: string | null;
}

export interface ReviewStats {
  attempts: number;
  judge_valid: number;
  exploits: number;
  pending: number;
  approved: number;
  rejected: number;
  target_before_patch_day: number;
  judge_precision: number | null;
  decisions_logged: number;
  by_edit_type: { edit_type: string; exploits: number; approved?: number; rejected?: number; pending?: number }[];
}

export const adminApi = {
  queue: (token: string, status: string) =>
    request<{ label: string; items: ReviewItem[]; stats: ReviewStats }>(
      `/api/admin/review?status=${status}`,
      { headers: { 'x-admin-token': token } },
    ),
  decide: (token: string, id: number, decision: 'approved' | 'rejected', reviewer: string, note = '') =>
    request<{ id: number; review_status: string; stats: ReviewStats }>(`/api/admin/review/${id}`, {
      method: 'POST',
      headers: { 'x-admin-token': token },
      body: JSON.stringify({ decision, reviewer, note }),
    }),
};

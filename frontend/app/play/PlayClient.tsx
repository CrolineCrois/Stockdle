'use client';

/**
 * The round loop: draw -> submit -> reveal -> score -> next.
 *
 * Timing note: the 10-second clock starts on the player's first stroke, not on
 * render, so reading the context card costs nothing and every player gets the
 * same ten seconds of drawing time. A separate idle timeout skips the round if
 * nobody touches the canvas at all.
 */

import { AnimatePresence, motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import Confetti from '@/components/Confetti';
import ContextCard from '@/components/ContextCard';
import DrawCanvas, {
  COVERAGE_TO_SUBMIT,
  type CanvasPhase,
  type DrawCanvasHandle,
} from '@/components/DrawCanvas';
import Nav from '@/components/Nav';
import ScorePanel from '@/components/ScorePanel';
import Toasts, { type ToastMessage } from '@/components/Toast';
import {
  CURVE_LEN,
  ROUND_SECONDS,
  api,
  type DailySummary,
  type GameRound,
  type NextRound,
  type SubmitResult,
} from '@/lib/api';
import { readPlayer } from '@/lib/player';
import { sound } from '@/lib/sound';

const IDLE_SKIP_MS = 30_000;
const REVEAL_MS = 1200;
const GHOST_MS = 560;
const ADMIN_TOKEN = process.env.NEXT_PUBLIC_ADMIN_TOKEN ?? 'tape-demo';

type Phase = 'loading' | 'draw' | 'submitting' | 'revealing' | 'revealed' | 'done' | 'error';

export default function PlayClient() {
  const router = useRouter();
  const params = useSearchParams();
  const mode = params.get('mode') === 'endless' ? 'endless' : 'daily';

  const canvasRef = useRef<DrawCanvasHandle>(null);
  const preloadRef = useRef<NextRound | null>(null);
  const startedRef = useRef(false);
  const submittedRef = useRef(false);
  const deadlineRef = useRef<number | null>(null);
  const idleRef = useRef<number | null>(null);
  const aiVersionRef = useRef(0);

  const [player, setPlayer] = useState(() => readPlayer());
  const [phase, setPhase] = useState<Phase>('loading');
  const [meta, setMeta] = useState<NextRound | null>(null);
  const [round, setRound] = useState<GameRound | null>(null);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [coverage, setCoverage] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(ROUND_SECONDS);
  const [streak, setStreak] = useState(0);
  const [total, setTotal] = useState(0);
  const [muted, setMuted] = useState(false);
  const [shake, setShake] = useState(0);
  const [confetti, setConfetti] = useState(0);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pushToast = useCallback((t: Omit<ToastMessage, 'id'>) => {
    setToasts((prev) => [...prev.slice(-2), { ...t, id: Date.now() + Math.random() }]);
  }, []);

  useEffect(() => {
    setMuted(sound.restore());
    const stored = readPlayer();
    if (!stored) {
      router.replace('/');
      return;
    }
    setPlayer(stored);
  }, [router]);

  // --- round loading ----------------------------------------------------
  const applyRound = useCallback((next: NextRound) => {
    setMeta(next);
    startedRef.current = false;
    submittedRef.current = false;
    deadlineRef.current = null;
    idleRef.current = Date.now() + IDLE_SKIP_MS;
    setCoverage(0);
    setSecondsLeft(ROUND_SECONDS);
    setResult(null);
    canvasRef.current?.reset();
    if (next.done || !next.round) {
      setRound(null);
      setPhase('done');
    } else {
      setRound(next.round);
      setPhase('draw');
    }
  }, []);

  const loadRound = useCallback(
    async (pid: string) => {
      if (preloadRef.current) {
        const queued = preloadRef.current;
        preloadRef.current = null;
        applyRound(queued);
        return;
      }
      setPhase('loading');
      try {
        applyRound(await api.nextRound(mode, pid));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load a round.');
        setPhase('error');
      }
    },
    [applyRound, mode],
  );

  useEffect(() => {
    if (!player) return;
    void loadRound(player.player_id);
    // Only on mount / player change — later rounds come from `next()`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player?.player_id]);

  // --- daily summary ----------------------------------------------------
  useEffect(() => {
    if (phase !== 'done' || mode !== 'daily' || !player) return;
    api.dailySummary(player.player_id).then(setSummary).catch(() => undefined);
  }, [phase, mode, player]);

  // --- submit -----------------------------------------------------------
  const submit = useCallback(
    async (opts: { skipped?: boolean } = {}) => {
      if (!player || !round || submittedRef.current) return;
      const curve = canvasRef.current?.getCurve() ?? null;
      const skipped = opts.skipped || curve === null;
      submittedRef.current = true;
      setPhase('submitting');

      const elapsed = startedRef.current && deadlineRef.current
        ? ROUND_SECONDS * 1000 - (deadlineRef.current - Date.now())
        : 0;

      try {
        const res = await api.submit(round.id, {
          player_id: player.player_id,
          curve: curve ?? new Array(CURVE_LEN).fill(0.5),
          time_ms: Math.max(0, Math.round(elapsed)),
          mode,
          skipped,
        });
        setResult(res);
        setStreak(res.streak);
        setTotal(res.player_total);
        setPhase('revealing');
        if (skipped) sound.fail();
        else sound.reveal();

        setTimeout(() => sound.ghost(), REVEAL_MS);
        setTimeout(() => {
          setPhase('revealed');
          if (res.score_breakdown.bullseye) {
            sound.bullseye();
            setShake((n) => n + 1);
            setConfetti((n) => n + 1);
          }
        }, REVEAL_MS + GHOST_MS);

        // Preload the next round while the reveal plays.
        api
          .nextRound(mode, player.player_id)
          .then((n) => {
            preloadRef.current = n;
          })
          .catch(() => undefined);

        // Did a retrain land?
        api
          .aiVersion()
          .then((v) => {
            if (v.version > aiVersionRef.current && aiVersionRef.current > 0) {
              pushToast({
                tone: 'ai',
                title: `⚡ TAPE AI v${v.version} deployed`,
                body: `learned from ${v.new_drawings} new drawings · blend error ${
                  v.rmse_blend?.toFixed(4) ?? '—'
                }`,
              });
            }
            aiVersionRef.current = v.version;
          })
          .catch(() => undefined);
      } catch (e) {
        submittedRef.current = false;
        setError(e instanceof Error ? e.message : 'Submit failed.');
        setPhase('error');
      }
    },
    [mode, player, pushToast, round],
  );

  // --- timers -----------------------------------------------------------
  const onFirstStroke = useCallback(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    deadlineRef.current = Date.now() + ROUND_SECONDS * 1000;
    sound.init();
  }, []);

  useEffect(() => {
    if (phase !== 'draw') return;
    const id = window.setInterval(() => {
      if (deadlineRef.current) {
        const left = (deadlineRef.current - Date.now()) / 1000;
        setSecondsLeft(Math.max(0, left));
        if (left <= 3 && left > 0 && Math.abs(left - Math.round(left)) < 0.06) sound.tick();
        if (left <= 0) {
          // Auto-submit when there is enough to score; otherwise skip at zero.
          void submit({ skipped: (canvasRef.current?.coverage() ?? 0) < COVERAGE_TO_SUBMIT });
        }
      } else if (idleRef.current && Date.now() > idleRef.current) {
        void submit({ skipped: true });
      }
    }, 80);
    return () => window.clearInterval(id);
  }, [phase, submit]);

  // --- next / keyboard --------------------------------------------------
  const next = useCallback(() => {
    if (!player) return;
    void loadRound(player.player_id);
  }, [loadRound, player]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if ((e.key === 'Enter' || e.key === ' ') && phase === 'revealed') {
        e.preventDefault();
        next();
      }
      if (e.key === 'Enter' && phase === 'draw' && coverage >= COVERAGE_TO_SUBMIT) {
        e.preventDefault();
        void submit();
      }
      // Demo shortcut: force an AI retrain live during the pitch.
      if (e.shiftKey && (e.key === 'R' || e.key === 'r')) {
        e.preventDefault();
        api
          .forceRetrain(ADMIN_TOKEN)
          .then(() =>
            pushToast({ tone: 'ai', title: 'Retrain queued', body: 'refitting blend weights…' }),
          )
          .catch(() =>
            pushToast({ tone: 'warn', title: 'Retrain rejected', body: 'check TAPE_ADMIN_TOKEN' }),
          );
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [coverage, next, phase, pushToast, submit]);

  const toggleMute = useCallback(() => {
    const nextMuted = !muted;
    sound.setMuted(nextMuted);
    setMuted(nextMuted);
    if (!nextMuted) sound.ghost();
  }, [muted]);

  const canvasPhase: CanvasPhase =
    phase === 'revealing' ? 'revealing' : phase === 'revealed' ? 'revealed' : 'draw';
  const ready = coverage >= COVERAGE_TO_SUBMIT;
  const timerPct = Math.max(0, Math.min(1, secondsLeft / ROUND_SECONDS));

  const copyShare = useCallback(async () => {
    if (!summary?.share) return;
    try {
      await navigator.clipboard.writeText(summary.share);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      pushToast({ tone: 'warn', title: 'Clipboard blocked', body: 'Select the text and copy it.' });
    }
  }, [pushToast, summary]);

  return (
    <>
      <Nav
        right={
          <>
            <span className="chip">
              {mode === 'daily' && meta?.of
                ? `Daily #${meta.daily_number ?? ''} · ${Math.min(meta.index, meta.of)}/${meta.of}`
                : 'Endless'}
            </span>
            <AnimatePresence>
              {streak > 0 && (
                <motion.span
                  key="streak"
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.6, opacity: 0 }}
                  className="chip border-you/50 bg-you/10 text-you"
                >
                  🔥 {streak}
                  {streak > 0 && (
                    <span className="num ml-1 opacity-80">
                      ×{Math.min(2, 1 + 0.1 * streak).toFixed(1)}
                    </span>
                  )}
                </motion.span>
              )}
            </AnimatePresence>
            <span className="chip num">{total.toLocaleString()}</span>
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? 'Unmute sound' : 'Mute sound'}
              className="rounded-lg border border-ink-700 bg-ink-800/70 px-2.5 py-1.5 text-sm hover:border-ink-600"
            >
              {muted ? '🔇' : '🔊'}
            </button>
          </>
        }
      />

      <Confetti fire={confetti} />
      <Toasts
        messages={toasts}
        onExpire={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))}
      />

      <main
        key={shake}
        className={`mx-auto w-full max-w-5xl px-4 pb-16 pt-5 ${shake ? 'animate-shake' : ''}`}
      >
        {phase === 'error' && (
          <div className="panel p-6">
            <p className="font-bold text-danger">Something broke.</p>
            <p className="mt-1 text-sm text-chalk-dim">{error}</p>
            <button type="button" onClick={next} className="btn-ghost mt-4">
              Try again
            </button>
          </div>
        )}

        {phase === 'loading' && (
          <div className="panel grid h-[60vh] place-items-center">
            <p className="animate-pulse text-sm text-chalk-dim">Cutting a fresh window…</p>
          </div>
        )}

        {phase === 'done' && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="panel space-y-5 p-6"
          >
            <div>
              <p className="label">Daily {summary ? `#${summary.number}` : ''} complete</p>
              <h1 className="mt-1 text-3xl font-black sm:text-4xl">Nice tape.</h1>
            </div>

            {summary && (
              <>
                <div className="flex flex-wrap gap-2">
                  {summary.scores.map((s, i) => (
                    <span
                      key={i}
                      className={`num grid h-14 w-14 place-items-center rounded-xl border text-lg font-bold ${
                        s >= 95
                          ? 'border-you bg-you/15 text-you'
                          : s >= 75
                            ? 'border-truth/50 bg-truth/10 text-truth'
                            : 'border-ink-700 bg-ink-800/70 text-chalk-dim'
                      }`}
                    >
                      {s}
                    </span>
                  ))}
                </div>

                <div className="rounded-xl border border-ink-700 bg-ink-950/60 p-4">
                  <p className="num break-words text-sm text-chalk">{summary.share}</p>
                  <button type="button" onClick={copyShare} className="btn-primary mt-3">
                    {copied ? 'Copied ✓' : 'Copy result'}
                  </button>
                </div>

                <p className="text-sm text-chalk-dim">
                  Total <span className="num font-bold text-chalk">{summary.total}</span> · beat the
                  AI on <span className="num font-bold text-chalk">{summary.beat_ai}</span> of{' '}
                  {summary.scores.length}
                </p>
              </>
            )}

            <div className="flex flex-wrap gap-3">
              <Link href="/play?mode=endless" className="btn-primary">
                Keep playing (Endless)
              </Link>
              <Link href="/leaderboard" className="btn-ghost">
                Leaderboard
              </Link>
              <Link href="/dashboard" className="btn-ghost">
                How the AI learned
              </Link>
            </div>
          </motion.div>
        )}

        {round && phase !== 'done' && phase !== 'error' && (
          <div className="space-y-3">
            <ContextCard round={round} />

            <div className="relative">
              <DrawCanvas
                ref={canvasRef}
                round={round}
                phase={canvasPhase}
                result={result}
                onCoverage={setCoverage}
                onFirstStroke={onFirstStroke}
                disabled={phase !== 'draw'}
              />

              {phase === 'draw' && !startedRef.current && (
                <div className="pointer-events-none absolute inset-0 grid place-items-center">
                  <p className="rounded-full border border-ink-700 bg-ink-950/80 px-4 py-2 text-sm text-chalk-dim">
                    Draw across the shaded area — the clock starts on your first stroke
                  </p>
                </div>
              )}
            </div>

            {phase === 'draw' || phase === 'submitting' ? (
              <div className="panel p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between text-xs text-chalk-dim">
                      <span>
                        {startedRef.current ? (
                          <span className="num font-bold text-chalk">
                            {secondsLeft.toFixed(1)}s
                          </span>
                        ) : (
                          <span>{ROUND_SECONDS}s once you start</span>
                        )}
                      </span>
                      <span className={ready ? 'text-truth' : ''}>
                        {Math.round(coverage * 100)}% drawn
                        {!ready && ` · need ${Math.round(COVERAGE_TO_SUBMIT * 100)}%`}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-800">
                      <div
                        className={`h-full rounded-full transition-[width] duration-100 ${
                          secondsLeft < 3 ? 'bg-danger' : 'bg-you'
                        }`}
                        style={{ width: `${timerPct * 100}%` }}
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={!ready || phase === 'submitting'}
                    onClick={() => void submit()}
                    className="btn-primary"
                  >
                    {phase === 'submitting' ? 'Scoring…' : 'Submit'}
                  </button>
                </div>
              </div>
            ) : null}

            {result && (phase === 'revealing' || phase === 'revealed') && (
              <ScorePanel
                result={result}
                show={phase === 'revealed'}
                onNext={next}
                nextLabel={
                  mode === 'daily' && meta?.of && meta.index >= meta.of
                    ? 'See your result'
                    : 'Next round'
                }
              />
            )}
          </div>
        )}
      </main>
    </>
  );
}

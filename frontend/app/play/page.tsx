'use client';

/**
 * One run: headlines until the lives run out.
 *
 *   editing  -> type; the meter updates 300ms after you stop; the clock runs
 *   judging  -> submitted; the clock is paused while the judge decides
 *   editing  -> (judge said "not a lie" and tries remain) the clock resumes
 *   result   -> snuck / caught / time's up / out of tries
 *   over     -> no lives left: the run summary
 *
 * The server owns the clock; the client only animates it, re-syncing to the
 * server's remaining time after every submission.
 */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import Confetti from '@/components/Confetti';
import HeadlineEditor from '@/components/HeadlineEditor';
import Nav from '@/components/Nav';
import OutcomeCard from '@/components/OutcomeCard';
import ShareCard from '@/components/ShareCard';
import SuspicionMeter from '@/components/SuspicionMeter';
import Toasts, { type ToastMessage } from '@/components/Toast';
import TimerBar from '@/components/TimerBar';
import {
  ApiError,
  api,
  noticesApi,
  type GameState,
  type MeterReading,
  type SubmitResult,
  type TracePoint,
} from '@/lib/api';
import { wordDiff } from '@/lib/diff';
import { readPlayer, signIn, type StoredPlayer } from '@/lib/player';
import { sound } from '@/lib/sound';

type Phase = 'loading' | 'editing' | 'judging' | 'result' | 'over' | 'error';
const METER_DEBOUNCE_MS = 300;

export default function Play() {
  const router = useRouter();
  const [player, setPlayer] = useState<StoredPlayer | null>(null);
  const [game, setGame] = useState<GameState | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [edited, setEdited] = useState('');
  const [meter, setMeter] = useState<MeterReading | null>(null);
  const [meterPending, setMeterPending] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [confetti, setConfetti] = useState(0);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const deadlineRef = useRef(0);          // performance.now() at which the clock hits 0
  const roundShownRef = useRef(0);        // performance.now() when the headline appeared
  const traceRef = useRef<TracePoint[]>([]);
  const lastTickRef = useRef(0);
  const meterSeqRef = useRef(0);
  const startedRef = useRef(false);       // React dev mode runs effects twice; start one run

  const round = game?.round ?? null;
  const rules = game?.rules;

  // --- setup ---------------------------------------------------------------
  const beginRound = useCallback((state: GameState) => {
    setGame(state);
    setResult(null);
    setNotice(null);
    setMeter(null);
    traceRef.current = [];
    if (state.run.over || !state.round || state.round.status !== 'active') {
      setPhase(state.run.over ? 'over' : 'result');
      return;
    }
    setEdited(state.round.headline.text);
    roundShownRef.current = performance.now();
    deadlineRef.current = performance.now() + state.round.remaining_s * 1000;
    setRemaining(state.round.remaining_s);
    setPhase('editing');
  }, []);

  useEffect(() => {
    setMuted(sound.restore());
    const stored = readPlayer();
    if (!stored) {
      router.replace('/');
      return;
    }
    if (startedRef.current) return;
    startedRef.current = true;
    signIn(stored.name)
      .then((info) => {
        const p = { player_id: info.player_id, name: info.name };
        setPlayer(p);
        // Patch days since your last visit that caught one of your exploits.
        noticesApi
          .list(p.player_id)
          .then(({ notices }) => {
            const byVersion = new Map<string, number>();
            notices.forEach((n) => byVersion.set(n.patched_in, (byVersion.get(n.patched_in) ?? 0) + 1));
            setToasts([...byVersion].map(([v, n], i) => ({
              id: Date.now() + i,
              title: `🛠 Patch ${v} closed ${n} of your exploit${n === 1 ? '' : 's'}`,
              body: 'The detector learned your trick. Find a new one.',
              tone: 'ai' as const,
            })));
          })
          .catch(() => undefined);
        return api.startRun(p.player_id);
      })
      .then(beginRound)
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Could not start a run.');
        setPhase('error');
      });
  }, [router, beginRound]);

  // --- the clock -------------------------------------------------------------
  const handleResult = useCallback(
    (res: SubmitResult) => {
      setGame(res.state);
      if (res.outcome === 'invalid' && !res.round_over) {
        // The judge ruled it not a lie; try again on the same clock.
        sound.invalid();
        setNotice(`${res.verdict.explanation ?? 'Not a lie.'} (${res.attempts_used}/${res.state.rules.max_attempts} tries used)`);
        deadlineRef.current = performance.now() + res.remaining_s * 1000;
        setRemaining(res.remaining_s);
        setPhase('editing');
        return;
      }
      if (res.outcome === 'snuck') {
        sound.sneak();
        setConfetti((n) => n + 1);
      }
      else if (res.outcome === 'invalid') sound.invalid();
      else sound.caught();
      setResult(res);
      setPhase('result');
    },
    [],
  );

  const sendTimeout = useCallback(async () => {
    if (!player || !round) return;
    setPhase('judging');
    try {
      const ms = Math.round(performance.now() - roundShownRef.current);
      handleResult(await api.timeout(round.id, player.player_id, edited, traceRef.current, ms));
    } catch (e) {
      // The server thinks there is still time (clock drift): resync and carry on.
      if (e instanceof ApiError && e.status === 409) {
        deadlineRef.current = performance.now() + 1000;
        setPhase('editing');
      } else {
        setError(e instanceof Error ? e.message : 'Lost the server.');
        setPhase('error');
      }
    }
  }, [player, round, edited, handleResult]);

  useEffect(() => {
    if (phase !== 'editing') return;
    const id = setInterval(() => {
      const left = (deadlineRef.current - performance.now()) / 1000;
      setRemaining(left);
      if (left <= 5 && left > 0 && Math.ceil(left) !== lastTickRef.current) {
        lastTickRef.current = Math.ceil(left);
        sound.tick();
      }
      if (left <= 0) {
        clearInterval(id);
        void sendTimeout();
      }
    }, 100);
    return () => clearInterval(id);
  }, [phase, sendTimeout]);

  // --- the live meter --------------------------------------------------------
  useEffect(() => {
    if (phase !== 'editing' || !player || !round) return;
    if (edited.trim() === round.headline.text.trim()) {
      setMeter(null);
      return;
    }
    const seq = ++meterSeqRef.current;
    setMeterPending(true);
    const t = setTimeout(async () => {
      try {
        const reading = await api.meter(round.id, player.player_id, edited);
        if (seq !== meterSeqRef.current) return;     // a newer keystroke won
        setMeter(reading);
        traceRef.current.push({
          t_ms: Math.round(performance.now() - roundShownRef.current),
          s: reading.suspicion,
          text: edited.slice(0, 300),
        });
      } catch {
        /* a dropped meter reading is harmless; the next keystroke retries */
      } finally {
        if (seq === meterSeqRef.current) setMeterPending(false);
      }
    }, METER_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [edited, phase, player, round]);

  // --- actions ---------------------------------------------------------------
  const submit = useCallback(async () => {
    if (phase !== 'editing' || !player || !round || !rules) return;
    const { changes } = wordDiff(round.headline.text, edited);
    if (changes === 0) {
      setNotice('Change at least one word.');
      return;
    }
    if (changes > rules.max_words) {
      setNotice(`That's ${changes} words — the limit is ${rules.max_words}.`);
      return;
    }
    const leftAtSubmit = (deadlineRef.current - performance.now()) / 1000;
    setPhase('judging');
    setNotice(null);
    try {
      const ms = Math.round(performance.now() - roundShownRef.current);
      handleResult(await api.submit(round.id, player.player_id, edited, traceRef.current, ms));
    } catch (e) {
      // Rejected before judging (400) or the judge was down (503): the clock
      // was paused server-side, so resume from where it stopped.
      deadlineRef.current = performance.now() + Math.max(0, leftAtSubmit) * 1000;
      setNotice(e instanceof Error ? e.message : 'Something went wrong.');
      setPhase('editing');
    }
  }, [phase, player, round, rules, edited, handleResult]);

  const next = useCallback(async () => {
    if (!player || !game) return;
    if (game.run.over) {
      setPhase('over');
      return;
    }
    setPhase('loading');
    try {
      beginRound(await api.nextRound(game.run.id, player.player_id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the next headline.');
      setPhase('error');
    }
  }, [player, game, beginRound]);

  const playAgain = useCallback(async () => {
    if (!player) return;
    setPhase('loading');
    beginRound(await api.startRun(player.player_id));
  }, [player, beginRound]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && phase === 'result') void next();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase, next]);

  // --- render ----------------------------------------------------------------
  const run = game?.run;
  const hud = run && (
    <>
      <span className="chip text-danger" aria-label={`${run.lives} lives`}>
        {'♥'.repeat(Math.max(0, run.lives))}
        <span className="text-chalk-faint">{'♥'.repeat(Math.max(0, run.max_lives - run.lives))}</span>
      </span>
      {run.streak > 0 && <span className="chip text-accent">🔥 {run.streak}</span>}
      <span className="chip num text-chalk">{run.score.toLocaleString()}</span>
      <button
        type="button"
        className="chip"
        onClick={() => {
          sound.setMuted(!muted);
          setMuted(!muted);
        }}
        aria-label={muted ? 'Unmute' : 'Mute'}
      >
        {muted ? '🔇' : '🔊'}
      </button>
    </>
  );

  const lastFive = phase === 'editing' && remaining <= 5;

  return (
    <>
      <Nav right={hud} />
      <Confetti fire={confetti} />
      <Toasts messages={toasts} onExpire={(id) => setToasts((t) => t.filter((m) => m.id !== id))} ttl={7000} />
      <main className="mx-auto w-full max-w-3xl space-y-4 px-4 pb-16 pt-5">
        {phase === 'error' && (
          <div className="panel p-5">
            <p className="font-semibold text-danger">Something broke.</p>
            <p className="mt-1 text-sm text-chalk-dim">{error}</p>
            <button type="button" className="btn-ghost mt-4" onClick={() => router.push('/')}>
              Back to start
            </button>
          </div>
        )}

        {phase === 'loading' && <p className="pt-10 text-center text-sm text-chalk-dim">Dealing a headline…</p>}

        {round && (phase === 'editing' || phase === 'judging') && rules && (
          <>
            <section className="panel space-y-3 p-4 sm:p-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="label">True headline</span>
                <span className="chip">{round.headline.source}</span>
                {round.is_bounty && <span className="chip border-accent/60 text-accent">★ Bounty · 3×</span>}
                <span className="chip">
                  try {round.attempts_used + 1}/{round.max_attempts}
                </span>
              </div>
              <h1 className="text-balance text-xl font-bold leading-snug sm:text-2xl">{round.headline.text}</h1>
              <p className="text-sm leading-relaxed text-chalk-dim">{round.headline.snippet}</p>
            </section>

            <section className="panel space-y-4 p-4 sm:p-5">
              <TimerBar remaining={remaining} total={round.timer_start_s} paused={phase === 'judging'} />
              <HeadlineEditor
                original={round.headline.text}
                value={edited}
                maxWords={rules.max_words}
                disabled={phase === 'judging'}
                onChange={(v) => {
                  sound.key();
                  setEdited(v);
                }}
                onSubmit={() => void submit()}
              />
              <div className="sticky bottom-0 z-20 -mx-4 space-y-3 border-t border-ink-700 bg-ink-950/95 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
              <SuspicionMeter
                value={meter?.suspicion ?? null}
                threshold={rules.threshold}
                nearFrom={rules.near_miss_from}
                pending={meterPending}
                shaking={lastFive}
              />
              {notice && <p className="rounded-lg bg-ink-950/60 px-3 py-2 text-sm text-chalk-dim">{notice}</p>}
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={phase === 'judging'}
                  onClick={() => void submit()}
                >
                  {phase === 'judging' ? 'Judging…' : 'Submit'}
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={phase === 'judging'}
                  onClick={() => setEdited(round.headline.text)}
                >
                  Reset
                </button>
              </div>
              </div>
            </section>
          </>
        )}

        {phase === 'result' && result && round && (
          <OutcomeCard result={result} original={round.headline.text} onNext={() => void next()} />
        )}

        {phase === 'over' && run && (
          <section className="panel p-6 text-center">
            <p className="label">Run over</p>
            <ShareCard run={run} />
            <div className="mt-5 flex flex-wrap justify-center gap-3">
              <button type="button" className="btn-primary" onClick={() => void playAgain()}>
                Play again
              </button>
              <button type="button" className="btn-ghost" onClick={() => router.push('/board')}>
                Exploit Board
              </button>
            </div>
          </section>
        )}
      </main>
    </>
  );
}

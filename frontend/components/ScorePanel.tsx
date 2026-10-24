'use client';

/**
 * Post-reveal panel: the legend, an animated score counter, bonus chips that
 * land one at a time, and the reveal facts.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';

import type { SubmitResult } from '@/lib/api';
import { DASH, SERIES } from '@/lib/palette';
import { sound } from '@/lib/sound';

function useCountUp(target: number, ms = 750, start = false) {
  const [value, setValue] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    if (!start) return;
    const t0 = performance.now();
    const step = () => {
      const t = Math.min(1, (performance.now() - t0) / ms);
      // easeOutCubic
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target, ms, start]);
  return value;
}

function Legend({ hasCrowd }: { hasCrowd: boolean }) {
  const items = [
    { label: 'You', color: SERIES.you, dash: undefined, width: 2.8 },
    { label: 'What happened', color: SERIES.truth, dash: undefined, width: 3.6 },
    ...(hasCrowd
      ? [{ label: 'Crowd', color: SERIES.crowd, dash: DASH.crowd.join(' '), width: 2.5 }]
      : []),
    { label: 'TAPE AI', color: SERIES.ai, dash: DASH.ai.join(' '), width: 2.5 },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-2 text-xs text-chalk-dim">
          <svg width="26" height="8" aria-hidden>
            <line
              x1="1"
              y1="4"
              x2="25"
              y2="4"
              stroke={it.color}
              strokeWidth={it.width}
              strokeDasharray={it.dash}
              strokeLinecap="round"
            />
          </svg>
          {it.label}
        </span>
      ))}
    </div>
  );
}

function RevealFacts({ result }: { result: SubmitResult }) {
  const r = result.reveal_info;
  const facts: Array<[string, string]> = [];
  if (r.ticker) facts.push(['Ticker', `${r.ticker}${r.name ? ` · ${r.name}` : ''}`]);
  if (r.region) facts.push(['Region', `${r.region}${r.city ? ` · ${r.city}` : ''}`]);
  if (r.term) facts.push(['Search term', r.term]);
  if (r.date ?? r.cut_at) facts.push(['Cut at', (r.date ?? r.cut_at ?? '').slice(0, 16)]);
  if (typeof r.forecast_high_f === 'number') {
    facts.push(['Forecast high', `${r.forecast_high_f.toFixed(0)}°F`]);
  }
  if (!facts.length) return null;

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      {facts.map(([k, v]) => (
        <div key={k}>
          <dt className="label">{k}</dt>
          <dd className="mt-0.5 truncate font-medium text-chalk" title={v}>
            {v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function ScorePanel({
  result,
  show,
  onNext,
  nextLabel = 'Next round',
}: {
  result: SubmitResult;
  show: boolean;
  onNext: () => void;
  nextLabel?: string;
}) {
  const sb = result.score_breakdown;
  const score = useCountUp(sb.total, 800, show);
  const [visibleBonuses, setVisibleBonuses] = useState(0);

  useEffect(() => {
    if (!show) {
      setVisibleBonuses(0);
      return;
    }
    const timers = sb.bonuses.map((b, i) =>
      setTimeout(() => {
        setVisibleBonuses(i + 1);
        sound.score(b.points);
      }, 700 + i * 230),
    );
    return () => timers.forEach(clearTimeout);
  }, [show, sb.bonuses]);

  const beatAI =
    sb.ai_rmse !== null && sb.rmse < sb.ai_rmse
      ? 'You beat the AI'
      : sb.ai_rmse !== null
        ? 'The AI beat you'
        : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={show ? { opacity: 1, y: 0 } : { opacity: 0, y: 14 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="panel space-y-4 p-4 sm:p-5"
    >
      <Legend hasCrowd={Boolean(result.crowd_curve)} />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="label">Score</p>
          <p className="num text-5xl font-black leading-none text-accent sm:text-6xl">
            {score}
          </p>
          <p className="mt-1.5 text-xs text-chalk-dim">
            <span className="num">{sb.base}</span> accuracy
            {sb.bonus_points > 0 && (
              <>
                {' + '}
                <span className="num">{sb.bonus_points}</span> bonus
              </>
            )}
            {sb.multiplier > 1 && (
              <>
                {' × '}
                <span className="num text-you">{sb.multiplier}</span> streak
              </>
            )}
          </p>
        </div>

        <div className="text-right text-xs text-chalk-dim">
          {beatAI && (
            <p className={sb.rmse < (sb.ai_rmse ?? 1) ? 'font-semibold text-truth' : ''}>
              {beatAI}
            </p>
          )}
          <p className="num mt-1">
            your error {sb.rmse.toFixed(3)}
            {sb.ai_rmse !== null && ` · AI ${sb.ai_rmse.toFixed(3)}`}
            {sb.crowd_rmse !== null && ` · crowd ${sb.crowd_rmse.toFixed(3)}`}
          </p>
          <p className="mt-1">
            {result.crowd_n >= 3
              ? `crowd line from ${result.crowd_n} drawings`
              : `${result.crowd_n}/3 drawings — crowd line not live yet`}
          </p>
        </div>
      </div>

      <div className="flex min-h-[34px] flex-wrap gap-2">
        <AnimatePresence>
          {sb.bonuses.slice(0, visibleBonuses).map((b) => (
            <motion.span
              key={b.key}
              initial={{ opacity: 0, scale: 0.7, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 420, damping: 22 }}
              className="inline-flex items-center gap-1.5 rounded-full border border-you/40 bg-you/10 px-3 py-1.5 text-xs font-semibold text-you"
            >
              {b.label}
              <span className="num opacity-80">+{b.points}</span>
            </motion.span>
          ))}
        </AnimatePresence>
        {sb.bullseye && visibleBonuses >= sb.bonuses.length && (
          <motion.span
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            className="inline-flex items-center gap-1.5 rounded-full bg-you px-3 py-1.5 text-xs font-black uppercase tracking-wide text-ink-950"
          >
            🎯 Bullseye
          </motion.span>
        )}
      </div>

      <RevealFacts result={result} />

      <button type="button" onClick={onNext} className="btn-primary w-full sm:w-auto">
        {nextLabel}
        <kbd className="rounded border border-ink-950/20 bg-ink-950/10 px-1.5 py-0.5 text-[10px] font-bold">
          ⏎
        </kbd>
      </button>
    </motion.div>
  );
}

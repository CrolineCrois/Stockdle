'use client';

/**
 * The drawing surface and the chart, on one canvas.
 *
 * Model: the hidden region is exactly 50 slots. A pointer x maps to one slot,
 * and each slot holds at most one y — a later stroke overwrites the slots it
 * passes over rather than layering a second line. Gaps between consecutive
 * samples are filled by linear interpolation, so a fast flick still produces a
 * continuous curve, and interior gaps are bridged on commit.
 *
 * Rendering runs in one rAF loop and never re-renders React during a stroke;
 * only coverage (throttled) and phase changes cross the boundary.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';

import {
  CURVE_LEN,
  VISIBLE_LEN,
  formatReal,
  type GameRound,
  type SubmitResult,
} from '@/lib/api';
import { DASH, GRID, SERIES } from '@/lib/palette';
import { sound } from '@/lib/sound';

const TOTAL = VISIBLE_LEN + CURVE_LEN;
const COVERAGE_TO_SUBMIT = 0.9;
const TRUTH_MS = 1200;
const GHOST_MS = 520;

const PAD = { left: 56, right: 14, top: 18, bottom: 30 };

export type CanvasPhase = 'draw' | 'revealing' | 'revealed';

export interface DrawCanvasHandle {
  /** The committed 50-point curve, or null if too little was drawn. */
  getCurve(): number[] | null;
  coverage(): number;
  reset(): void;
}

interface Props {
  round: GameRound;
  phase: CanvasPhase;
  result: SubmitResult | null;
  onCoverage?: (fraction: number) => void;
  onFirstStroke?: () => void;
  disabled?: boolean;
}

const COLORS = {
  grid: GRID,
  visible: '#cbd5f5',
  you: SERIES.you,
  truth: SERIES.truth,
  crowd: SERIES.crowd,
  robot: SERIES.ai,
};

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

/** Fill NaN gaps between the first and last drawn slot. */
function interpolate(slots: Float32Array): number[] | null {
  const idx: number[] = [];
  for (let i = 0; i < slots.length; i += 1) if (!Number.isNaN(slots[i])) idx.push(i);
  if (idx.length === 0) return null;

  const out = new Array<number>(slots.length);
  const first = idx[0];
  const last = idx[idx.length - 1];
  for (let i = 0; i < first; i += 1) out[i] = slots[first];
  for (let i = last + 1; i < slots.length; i += 1) out[i] = slots[last];

  for (let k = 0; k < idx.length - 1; k += 1) {
    const a = idx[k];
    const b = idx[k + 1];
    out[a] = slots[a];
    for (let i = a + 1; i < b; i += 1) out[i] = lerp(slots[a], slots[b], (i - a) / (b - a));
  }
  out[last] = slots[last];
  return out.map((v) => Math.min(1, Math.max(0, v)));
}

const DrawCanvas = forwardRef<DrawCanvasHandle, Props>(function DrawCanvas(
  { round, phase, result, onCoverage, onFirstStroke, disabled = false },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const slotsRef = useRef<Float32Array>(new Float32Array(CURVE_LEN).fill(NaN));
  const drawingRef = useRef(false);
  const lastSlotRef = useRef<number | null>(null);
  const strokeStartedRef = useRef(false);
  const sizeRef = useRef({ w: 900, h: 420 });
  const revealStartRef = useRef<number | null>(null);
  const phaseRef = useRef<CanvasPhase>(phase);
  const resultRef = useRef<SubmitResult | null>(result);
  const roundRef = useRef<GameRound>(round);
  const [, forceTick] = useState(0);

  phaseRef.current = phase;
  resultRef.current = result;
  roundRef.current = round;

  // --- geometry ---------------------------------------------------------
  const xAt = useCallback((i: number) => {
    const { w } = sizeRef.current;
    const inner = w - PAD.left - PAD.right;
    return PAD.left + (i / (TOTAL - 1)) * inner;
  }, []);

  const yAt = useCallback((v: number) => {
    const { h } = sizeRef.current;
    const inner = h - PAD.top - PAD.bottom;
    return PAD.top + (1 - v) * inner;
  }, []);

  const slotFromX = useCallback((px: number) => {
    const { w } = sizeRef.current;
    const inner = w - PAD.left - PAD.right;
    const i = ((px - PAD.left) / inner) * (TOTAL - 1);
    return Math.round(i) - VISIBLE_LEN;
  }, []);

  const valueFromY = useCallback((py: number) => {
    const { h } = sizeRef.current;
    const inner = h - PAD.top - PAD.bottom;
    return Math.min(1, Math.max(0, 1 - (py - PAD.top) / inner));
  }, []);

  // --- input ------------------------------------------------------------
  const reportCoverage = useCallback(() => {
    if (!onCoverage) return;
    let n = 0;
    const s = slotsRef.current;
    for (let i = 0; i < s.length; i += 1) if (!Number.isNaN(s[i])) n += 1;
    onCoverage(n / CURVE_LEN);
  }, [onCoverage]);

  const paintSlot = useCallback(
    (slot: number, value: number) => {
      const s = slotsRef.current;
      const clamped = Math.min(CURVE_LEN - 1, Math.max(0, slot));
      const prev = lastSlotRef.current;
      if (prev === null || prev === clamped) {
        s[clamped] = value;
      } else {
        // Bridge the jump so a fast flick leaves no holes.
        const from = Math.min(prev, clamped);
        const to = Math.max(prev, clamped);
        const startV = Number.isNaN(s[prev]) ? value : s[prev];
        for (let i = from; i <= to; i += 1) {
          const t = (i - prev) / (clamped - prev);
          s[i] = prev < clamped ? lerp(startV, value, t) : lerp(value, startV, 1 - t);
        }
        s[clamped] = value;
      }
      lastSlotRef.current = clamped;
    },
    [],
  );

  const handlePointer = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (phaseRef.current !== 'draw' || disabled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const value = valueFromY(py);
      paintSlot(slotFromX(px), value);
      sound.draw(value);
      reportCoverage();
    },
    [disabled, paintSlot, reportCoverage, slotFromX, valueFromY],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (phaseRef.current !== 'draw' || disabled) return;
      e.preventDefault();
      canvasRef.current?.setPointerCapture(e.pointerId);
      drawingRef.current = true;
      lastSlotRef.current = null;
      if (!strokeStartedRef.current) {
        strokeStartedRef.current = true;
        onFirstStroke?.();
      }
      handlePointer(e);
    },
    [disabled, handlePointer, onFirstStroke],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      e.preventDefault();
      handlePointer(e);
    },
    [handlePointer],
  );

  const endStroke = useCallback(() => {
    drawingRef.current = false;
    lastSlotRef.current = null;
    reportCoverage();
  }, [reportCoverage]);

  useImperativeHandle(
    ref,
    () => ({
      getCurve() {
        const s = slotsRef.current;
        let n = 0;
        for (let i = 0; i < s.length; i += 1) if (!Number.isNaN(s[i])) n += 1;
        if (n / CURVE_LEN < COVERAGE_TO_SUBMIT) return null;
        return interpolate(s);
      },
      coverage() {
        const s = slotsRef.current;
        let n = 0;
        for (let i = 0; i < s.length; i += 1) if (!Number.isNaN(s[i])) n += 1;
        return n / CURVE_LEN;
      },
      reset() {
        slotsRef.current = new Float32Array(CURVE_LEN).fill(NaN);
        lastSlotRef.current = null;
        strokeStartedRef.current = false;
        revealStartRef.current = null;
        reportCoverage();
      },
    }),
    [reportCoverage],
  );

  // New round: wipe the board.
  useEffect(() => {
    slotsRef.current = new Float32Array(CURVE_LEN).fill(NaN);
    lastSlotRef.current = null;
    strokeStartedRef.current = false;
    revealStartRef.current = null;
    reportCoverage();
    forceTick((n) => n + 1);
  }, [round.id, reportCoverage]);

  useEffect(() => {
    if (phase === 'revealing') revealStartRef.current = performance.now();
  }, [phase]);

  // --- sizing -----------------------------------------------------------
  useEffect(() => {
    const box = boxRef.current;
    const canvas = canvasRef.current;
    if (!box || !canvas) return;
    const resize = () => {
      const rect = box.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(280, rect.width);
      const h = Math.max(240, rect.height);
      sizeRef.current = { w, h };
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const obs = new ResizeObserver(resize);
    obs.observe(box);
    window.addEventListener('orientationchange', resize);
    return () => {
      obs.disconnect();
      window.removeEventListener('orientationchange', resize);
    };
  }, []);

  // --- render loop ------------------------------------------------------
  useEffect(() => {
    let raf = 0;
    const render = () => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (ctx && canvas) paint(ctx);
      raf = requestAnimationFrame(render);
    };

    const line = (
      ctx: CanvasRenderingContext2D,
      pts: Array<[number, number]>,
      style: string,
      width: number,
      dash: number[] = [],
      alpha = 1,
    ) => {
      if (pts.length < 2) return;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.setLineDash(dash);
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i += 1) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.stroke();
      ctx.restore();
    };

    const paint = (ctx: CanvasRenderingContext2D) => {
      const { w, h } = sizeRef.current;
      const r = roundRef.current;
      const res = resultRef.current;
      const ph = phaseRef.current;
      const plotTop = PAD.top;
      const plotBottom = h - PAD.bottom;
      const cutX = xAt(VISIBLE_LEN - 1);

      ctx.clearRect(0, 0, w, h);

      // Prediction region tint.
      ctx.fillStyle = 'rgba(240,180,41,0.045)';
      ctx.fillRect(cutX, plotTop, xAt(TOTAL - 1) - cutX, plotBottom - plotTop);

      // Gridlines + real-unit labels.
      ctx.save();
      ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
      ctx.fillStyle = 'rgba(148,163,196,0.72)';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let k = 0; k <= 4; k += 1) {
        const v = k / 4;
        const y = yAt(v);
        ctx.strokeStyle = COLORS.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(w - PAD.right, y);
        ctx.stroke();
        ctx.fillText(formatReal(v, r.scale), PAD.left - 8, y);
      }
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(148,163,196,0.55)';
      ctx.fillText(r.scale.y_label, PAD.left, h - 10);
      ctx.textAlign = 'right';
      ctx.fillText(`${r.x_label} →`, w - PAD.right, h - 10);
      ctx.restore();

      // Visible history.
      const visPts = r.visible.map((v, i) => [xAt(i), yAt(v)] as [number, number]);
      line(ctx, visPts, COLORS.visible, 2.2);

      // The "now" line.
      ctx.save();
      ctx.setLineDash([5, 6]);
      ctx.strokeStyle = 'rgba(148,163,196,0.65)';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(cutX, plotTop);
      ctx.lineTo(cutX, plotBottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(148,163,196,0.8)';
      ctx.font = '10px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('NOW', cutX, plotTop - 6);
      ctx.restore();

      const anchor: [number, number] = [cutX, yAt(r.visible[r.visible.length - 1])];

      // Player's line. The start is visually snapped to the last visible point.
      const slots = slotsRef.current;
      const playerPts: Array<[number, number]> = [anchor];
      const committed = res ? null : interpolate(slots);
      const source = committed ?? slots;
      for (let i = 0; i < CURVE_LEN; i += 1) {
        const v = Array.isArray(source) ? source[i] : source[i];
        if (!Number.isNaN(v) && v !== undefined) {
          playerPts.push([xAt(VISIBLE_LEN + i), yAt(v)]);
        }
      }
      if (playerPts.length > 1) {
        ctx.save();
        ctx.shadowColor = 'rgba(240,180,41,0.5)';
        ctx.shadowBlur = 12;
        line(ctx, playerPts, COLORS.you, 3);
        ctx.restore();
      }

      // Reveal sequence.
      if (res && (ph === 'revealing' || ph === 'revealed')) {
        const started = revealStartRef.current ?? performance.now();
        const elapsed = performance.now() - started;
        const truthT = ph === 'revealed' ? 1 : Math.min(1, elapsed / TRUTH_MS);
        const shown = Math.max(2, Math.round(truthT * CURVE_LEN));

        // Shaded gap between the player and the truth, up to the trace head.
        const drawn = interpolate(slots) ?? res.truth;
        ctx.save();
        ctx.globalAlpha = 0.16;
        ctx.fillStyle = res.score_breakdown.base >= 75 ? COLORS.truth : '#fb7185';
        ctx.beginPath();
        ctx.moveTo(anchor[0], anchor[1]);
        for (let i = 0; i < shown; i += 1) ctx.lineTo(xAt(VISIBLE_LEN + i), yAt(res.truth[i]));
        for (let i = shown - 1; i >= 0; i -= 1) ctx.lineTo(xAt(VISIBLE_LEN + i), yAt(drawn[i]));
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        const truthPts: Array<[number, number]> = [anchor];
        for (let i = 0; i < shown; i += 1) {
          truthPts.push([xAt(VISIBLE_LEN + i), yAt(res.truth[i])]);
        }
        ctx.save();
        ctx.shadowColor = 'rgba(0,160,0,0.75)';
        ctx.shadowBlur = 14;
        line(ctx, truthPts, COLORS.truth, 3.6);
        ctx.restore();

        // Trace head.
        const head = truthPts[truthPts.length - 1];
        ctx.save();
        ctx.fillStyle = COLORS.truth;
        ctx.shadowColor = COLORS.truth;
        ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.arc(head[0], head[1], truthT < 1 ? 5 : 3.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Ghosts fade in once the truth has landed.
        const ghostAlpha = Math.min(1, Math.max(0, (elapsed - TRUTH_MS) / GHOST_MS));
        if (ghostAlpha > 0) {
          if (res.crowd_curve) {
            const pts: Array<[number, number]> = [
              anchor,
              ...res.crowd_curve.map(
                (v, i) => [xAt(VISIBLE_LEN + i), yAt(v)] as [number, number],
              ),
            ];
            line(ctx, pts, COLORS.crowd, 2.2, [...DASH.crowd], ghostAlpha * 0.95);
          }
          const aiPts: Array<[number, number]> = [
            anchor,
            ...res.ai_curve.map((v, i) => [xAt(VISIBLE_LEN + i), yAt(v)] as [number, number]),
          ];
          line(ctx, aiPts, COLORS.robot, 2.2, [...DASH.ai], ghostAlpha * 0.95);
        }

        // Turning point marker, when the round had one.
        const tp = res.score_breakdown.turning_point;
        if (tp && ghostAlpha > 0.4) {
          const x = xAt(VISIBLE_LEN + tp.index);
          const y = yAt(res.truth[tp.index]);
          ctx.save();
          ctx.globalAlpha = ghostAlpha;
          ctx.strokeStyle = tp.hit ? COLORS.you : 'rgba(148,163,196,0.8)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, 9, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
      }

      // Anchor dot, always.
      ctx.save();
      ctx.fillStyle = COLORS.visible;
      ctx.beginPath();
      ctx.arc(anchor[0], anchor[1], 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    };

    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [xAt, yAt]);

  return (
    <div
      ref={boxRef}
      className="relative h-[clamp(240px,46vh,460px)] w-full overflow-hidden rounded-2xl border border-ink-700 bg-ink-900/70"
    >
      <canvas
        ref={canvasRef}
        className={
          phase === 'draw' && !disabled
            ? 'block cursor-crosshair touch-none'
            : 'block touch-none'
        }
        style={{ touchAction: 'none' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endStroke}
        onPointerCancel={endStroke}
        onPointerLeave={endStroke}
      />
    </div>
  );
});

export default DrawCanvas;
export { COVERAGE_TO_SUBMIT };

/**
 * The one place chart colours are defined — the canvas, the legend and the
 * dashboard all read from here, so "the blue line" means the AI everywhere.
 *
 * Validated with the data-viz palette validator against the app's chart
 * surface (#0b1020) in dark mode:
 *
 *   SERIES (4, all-pairs)  blue / amber / magenta / green
 *     lightness band PASS · chroma PASS · contrast PASS
 *     worst all-pairs CVD ΔE 6.9 — inside the 6–8 floor band, which is legal
 *     only *with* secondary encoding. Every surface that draws all four
 *     supplies it: distinct line styles (solid / solid-heavy / dashed /
 *     dotted), an always-present legend, and direct labels in the score panel.
 *
 *   DASHBOARD (3, all-pairs)  model / crowd / blend
 *     ALL CHECKS PASS (worst CVD ΔE 13.2).
 *
 *   DIVERGING  blue ↔ red with a neutral grey midpoint, for signed bias.
 *
 * Re-run after any change:
 *   node scripts/validate_palette.js "#3987e5,#c98500,#d55181,#008300" \
 *        --mode dark --surface "#0b1020" --pairs all
 */

export const SERIES = {
  /** The player's own line. */
  you: '#c98500',
  /** What actually happened. Drawn heaviest — it is the hero of the reveal. */
  truth: '#008300',
  /** Pointwise mean of every drawing on this round. */
  crowd: '#d55181',
  /** The TAPE forecaster. */
  ai: '#3987e5',
} as const;

/** UI chrome only (buttons, the big score). Same hue family as SERIES.you. */
export const ACCENT = '#f0b429';

export const DIVERGING = {
  /** Drawn above the truth — over-prediction. */
  over: '#e66767',
  /** Drawn below the truth — under-prediction. */
  under: '#3987e5',
  midpoint: '#383835',
} as const;

export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  critical: '#d03b3b',
} as const;

export const SURFACE = '#0b1020';
export const GRID = 'rgba(148,163,196,0.10)';
export const INK_DIM = 'rgba(148,163,196,0.72)';

/** Line styles double as the secondary encoding the 4-series palette needs. */
export const DASH = {
  you: undefined as number[] | undefined,
  truth: undefined as number[] | undefined,
  crowd: [7, 5],
  ai: [1.5, 4],
} as const;

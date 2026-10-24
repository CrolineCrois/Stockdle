/**
 * Chart tokens for /lab. Dark-only app, so these are the reference palette's
 * dark steps, validated on the panel surface (#0b1020) with the dataviz
 * validator: all checks pass all-pairs (worst CVD ΔE 9.4, contrast >= 3:1).
 *
 * Colour follows the entity, everywhere on the page:
 *   human exploits      -> slot 1 blue
 *   machine-made fakes  -> slot 2 orange
 *   true headlines      -> slot 3 aqua
 */

export const SURFACE = '#0b1020';

export const SERIES = {
  human: '#3987e5',
  machine: '#d95926',
  truth: '#199e70',
} as const;

export const INK = {
  primary: '#e8edf7',
  secondary: '#94a3c4',
  muted: '#5a6a8c',
  grid: '#1c2742',
  axis: '#2b3a5c',
} as const;

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`;

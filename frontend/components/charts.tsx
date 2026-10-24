'use client';

/**
 * Shared chart furniture for the dashboard.
 *
 * Conventions applied throughout (see lib/palette.ts for the colour report):
 * recessive grid and axes, thin marks, a legend whenever two or more series
 * share a plot, selective direct labels rather than a number on every point,
 * a hover tooltip on every plot, and a toggleable table view so identity is
 * never carried by colour alone.
 */

import { useState } from 'react';
import { Tooltip } from 'recharts';

import { GRID, INK_DIM } from '@/lib/palette';

export const AXIS = {
  stroke: 'rgba(148,163,196,0.35)',
  tick: { fill: INK_DIM, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: 'rgba(148,163,196,0.25)' },
} as const;

export const GRID_PROPS = {
  stroke: GRID,
  strokeDasharray: '0',
  vertical: false,
} as const;

export function ChartTooltip({
  active,
  payload,
  label,
  format = (v: number) => v.toLocaleString(),
  labelPrefix = '',
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string; dataKey?: string }>;
  label?: string | number;
  format?: (v: number) => string;
  labelPrefix?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-3 py-2 shadow-panel">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-chalk-faint">
        {labelPrefix}
        {label}
      </p>
      <ul className="mt-1 space-y-0.5">
        {payload.map((p) => (
          <li key={p.dataKey ?? p.name} className="flex items-center gap-2 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-sm"
              style={{ background: p.color }}
              aria-hidden
            />
            <span className="text-chalk-dim">{p.name}</span>
            <span className="num ml-auto font-semibold text-chalk">
              {typeof p.value === 'number' ? format(p.value) : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Recharts needs the element, not a component reference, for `content`. */
export function tooltip(props: Parameters<typeof ChartTooltip>[0] = {}) {
  return (
    <Tooltip
      cursor={{ stroke: 'rgba(148,163,196,0.3)', strokeWidth: 1 }}
      content={<ChartTooltip {...props} />}
    />
  );
}

export function Panel({
  title,
  kicker,
  caption,
  table,
  children,
  wide = false,
}: {
  title: string;
  kicker?: string;
  caption?: string;
  table?: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className={`panel p-4 sm:p-5 ${wide ? 'lg:col-span-2' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          {kicker && <p className="label">{kicker}</p>}
          <h2 className="mt-0.5 text-lg font-bold text-chalk">{title}</h2>
        </div>
        {table && (
          <button
            type="button"
            onClick={() => setShowTable((s) => !s)}
            className="rounded-lg border border-ink-700 px-2.5 py-1 text-[11px] text-chalk-dim transition hover:border-ink-600 hover:text-chalk"
            aria-expanded={showTable}
          >
            {showTable ? 'Show chart' : 'Show table'}
          </button>
        )}
      </div>
      {caption && <p className="mt-1.5 text-sm text-chalk-dim">{caption}</p>}
      <div className="mt-4">
        {showTable && table ? <div className="overflow-x-auto">{table}</div> : children}
      </div>
    </section>
  );
}

export function DataTable({
  head,
  rows,
}: {
  head: string[];
  rows: Array<Array<string | number>>;
}) {
  return (
    <table className="w-full min-w-[360px] text-sm">
      <thead>
        <tr className="border-b border-ink-800 text-left">
          {head.map((h) => (
            <th key={h} className="label px-2 py-2 font-semibold">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-b border-ink-800/60 last:border-0">
            {r.map((c, j) => (
              <td
                key={j}
                className={`px-2 py-2 ${j === 0 ? 'text-chalk' : 'num text-right text-chalk-dim'}`}
              >
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="panel p-4">
      <p className="label">{label}</p>
      <p
        className="num mt-1 text-3xl font-black leading-none"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-xs text-chalk-dim">{sub}</p>}
    </div>
  );
}

export function Empty({ what }: { what: string }) {
  return (
    <div className="grid h-40 place-items-center rounded-xl border border-dashed border-ink-700">
      <p className="px-6 text-center text-sm text-chalk-dim">{what}</p>
    </div>
  );
}

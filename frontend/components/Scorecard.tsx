'use client';

/**
 * The AI scorecard on /learn, organised as the questions people actually ask:
 *   1. Is it catching more real players' lies?        (live play, per version)
 *   2. Did it learn the tricks that beat earlier versions?
 *                                                      (held-out player lies, grouped by which
 *                                                       version they fooled; each group only
 *                                                       scores versions it wasn't picked against)
 *   3. Did it get worse at everyday headlines?         (overall accuracy; flat is good)
 *   then the detailed breakdown and the first-glance meter.
 * Every chart title says which direction is good. Whiskers are 95% ranges.
 */

import { useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { CI, LearningSummary, LearningVersion } from '@/lib/api';
import { INK, SERIES, pct } from '@/lib/viz';

const AXIS = { stroke: INK.axis, tick: { fill: INK.muted, fontSize: 12 }, tickLine: false } as const;
const END = [4, 4, 0, 0] as [number, number, number, number];
const LEGEND = {
  wrapperStyle: { fontSize: 12 },
  formatter: (v: string) => <span style={{ color: INK.secondary }}>{v}</span>,
};
// One fixed colour per version (oldest grey, newest the player blue).
const VERSION_COLOURS = ['#94a3c4', '#c79a2c', SERIES.human, '#b26fd6', '#4fb8c9'];
const colourOf = (names: string[], name: string) => VERSION_COLOURS[names.indexOf(name) % VERSION_COLOURS.length];

// null when there's no range to draw: a zero-width whisker renders duplicate
// line segments, which Recharts keys by coordinates (duplicate-key warning).
const err = (c?: CI | null) => {
  if (!c || c.value === null) return null;
  const e = [c.value - (c.lo ?? c.value), (c.hi ?? c.value) - c.value];
  return e[0] > 0 || e[1] > 0 ? e : null;
};
// Below this many examples a range is meaningless; show the raw count instead.
const SMALL_N = 20;
const count = (c: CI) => `${Math.round((c.value ?? 0) * c.n)} of ${c.n}`;
const ciText = (c?: CI | null) =>
  !c || c.value === null
    ? '—'
    : c.n < SMALL_N
      ? `${pct(c.value)} (${count(c)})`
      : `${pct(c.value)} [${pct(c.lo)}–${pct(c.hi)}], n=${c.n}`;

function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-3 py-2 text-xs">
      <p className="font-semibold text-chalk">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="mt-1 flex items-center gap-2 text-chalk-dim">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} aria-hidden />
          {p.name}: <span className="num text-chalk">{pct(p.value)}</span>
          {p.payload?.[`${p.dataKey}Count`] && <span className="text-chalk-faint">({p.payload[`${p.dataKey}Count`]})</span>}
        </p>
      ))}
    </div>
  );
}

function Question({ n, title, good, children }: { n: number; title: string; good: string; children?: React.ReactNode }) {
  return (
    <div className="mt-8">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-bold">
          <span className="num mr-2 text-accent">{n}</span>
          {title}
        </h3>
        <span className="chip text-xs">{good}</span>
      </div>
      {children && <div className="mt-1 space-y-1 text-sm text-chalk-dim">{children}</div>}
    </div>
  );
}

function SimpleTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-chalk-faint">
            {head.map((h) => (
              <th key={h} className="py-2 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-ink-800">
              {r.map((c, j) => (
                <td key={j} className={`py-2 pr-3 ${j === 0 ? 'font-semibold' : 'num text-chalk-dim'}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- 1. live play ------------------------------------------------------------
function LiveChart({ data, names }: { data: LearningSummary; names: string[] }) {
  const rows = names.map((name) => {
    const c = data.live.find((x) => x.version === name)?.caught;
    const live = data.verifier.find((v) => v.name === name)?.is_current;
    return {
      name: `${name}${live ? ' (live)' : ''} · ${c ? `${c.n} lies${c.n < SMALL_N ? ', early' : ''}` : 'none yet'}`,
      key: name,
      value: c?.value ?? null,
      err: c && c.n >= SMALL_N ? err(c) : null,
      label: c ? pct(c.value) : '',
    };
  });
  return (
    <div className="h-60">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 24, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar name="Players’ lies caught" dataKey="value" radius={END} maxBarSize={72} fill={SERIES.human}>
            <ErrorBar dataKey="err" width={5} stroke={INK.primary} />
            <LabelList dataKey="label" position="insideBottom" offset={10} fill="#ffffff" fontSize={13} fontWeight={700} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- 2. fair comparison on held-out player lies --------------------------------
function FairChart({ data, names }: { data: LearningSummary; names: string[] }) {
  const groups = names.filter((g) => data.verifier.some((v) => v.benchmark?.by_fooled?.[g]));
  const rows = groups.map((g) => {
    const row: Record<string, any> = { name: `Lies that fooled ${g}` };
    for (const v of data.verifier) {
      if (v.name === g) continue; // rigged against the version that was picked against
      const c = v.benchmark?.by_fooled?.[g];
      if (!c) continue;
      row[v.name] = c.value;
      row[`${v.name}Count`] = count(c);
    }
    return row;
  });
  const shown = names.filter((n) => rows.some((r) => r[n] !== undefined));
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows} barGap={4} margin={{ top: 24, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Legend {...LEGEND} />
          {shown.map((n) => (
            <Bar key={n} name={n} dataKey={n} radius={END} maxBarSize={56} fill={colourOf(names, n)}>
              <LabelList dataKey={`${n}Count`} position="top" offset={8} fill={INK.secondary} fontSize={11} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- 3. overall accuracy -----------------------------------------------------------
/** Accuracy on a test that is half true headlines, half AI-written lies: the
 * average of lies caught and true headlines left alone (unbiased sets only). */
function overall(v: LearningVersion) {
  const b = v.benchmark;
  if (!b || b.lies_caught.value == null || b.true_flagged.value == null) return null;
  const caught = b.lies_caught.value;
  const correctTrue = 1 - b.true_flagged.value;
  const value = (caught + correctTrue) / 2;
  const se = Math.sqrt((caught * (1 - caught)) / b.lies_caught.n + (correctTrue * (1 - correctTrue)) / b.true_flagged.n) / 2;
  return { value, lo: Math.max(0, value - 1.96 * se), hi: Math.min(1, value + 1.96 * se) };
}

function OverallChart({ versions }: { versions: LearningVersion[] }) {
  const rows = versions.map((v) => {
    const o = overall(v);
    return {
      name: v.is_current ? `${v.name} (live)` : v.name,
      value: o?.value ?? null,
      err: o ? [o.value - o.lo, o.hi - o.value] : null,
    };
  });
  return (
    <div className="h-52">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 22, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar name="Right on everyday headlines" dataKey="value" fill={INK.secondary} radius={END} maxBarSize={72}>
            <ErrorBar dataKey="err" width={5} stroke={INK.primary} />
            <LabelList dataKey="value" position="top" offset={12} formatter={(v: number) => pct(v)} fill={INK.primary} fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- details: the two unbiased sets, separately ---------------------------------------
function BreakdownChart({ versions }: { versions: LearningVersion[] }) {
  const rows = versions.map((v) => ({
    name: v.name,
    machine: v.benchmark?.lies_caught.value ?? null,
    machineErr: err(v.benchmark?.lies_caught),
    truth: v.benchmark?.true_flagged.value ?? null,
    truthErr: err(v.benchmark?.true_flagged),
  }));
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows} barGap={2} margin={{ top: 22, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Legend {...LEGEND} />
          <Bar name="AI-written lies caught (higher is better)" dataKey="machine" fill={SERIES.machine} radius={END}>
            <ErrorBar dataKey="machineErr" width={5} stroke={INK.secondary} />
            <LabelList dataKey="machine" position="top" offset={12} formatter={(v: number) => pct(v)} fill={INK.secondary} fontSize={11} />
          </Bar>
          <Bar name="True headlines wrongly flagged (lower is better)" dataKey="truth" fill={SERIES.truth} radius={END}>
            <ErrorBar dataKey="truthErr" width={5} stroke={INK.secondary} />
            <LabelList dataKey="truth" position="top" offset={12} formatter={(v: number) => pct(v)} fill={INK.secondary} fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Hide numbers measured on different tests (or a different verdict rule) from
 * the live version: comparing them would mislead. */
function comparable<T extends LearningVersion>(versions: T[], sizesOnly = false): T[] {
  // The meter's glance entry also records which fact-checker it used, so meter
  // versions are compared on test-set sizes only.
  const norm = (set?: (number | string)[]) => JSON.stringify(sizesOnly ? (set ?? []).filter((x) => typeof x === 'number') : set);
  const ref = versions.find((v) => v.is_current)?.benchmark?.set;
  if (!ref) return versions;
  const key = norm(ref);
  return versions.map((v) => (v.benchmark && norm(v.benchmark.set) !== key ? { ...v, benchmark: null } : v));
}

export default function Scorecard({ data: raw }: { data: LearningSummary }) {
  const data = { ...raw, verifier: comparable(raw.verifier), meter: comparable(raw.meter, true) };
  const [tables, setTables] = useState(false);
  const names = data.verifier.map((v) => v.name);
  const live = data.verifier.find((v) => v.is_current);
  const liveBig = [...data.live].reverse().find((x) => x.caught.n >= SMALL_N);
  const liveOverall = live ? overall(live) : null;
  const pending = data.verifier.filter((v) => !v.benchmark).map((v) => v.name);
  const firstLive = data.live.find((x) => x.version === names[0])?.caught;

  return (
    <section className="panel mt-8 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="label">The AI’s scorecard</p>
          <h2 className="mt-1 text-xl font-bold">Is the fact-checker getting better?</h2>
        </div>
        <button type="button" className="chip shrink-0" onClick={() => setTables((t) => !t)}>
          {tables ? 'Show charts' : 'Show tables'}
        </button>
      </div>
      <p className="mt-2 text-sm text-chalk-dim">
        Each “patch day” retrains the fact-checker on lies players snuck past the previous version. Three questions
        tell you whether that worked.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-ink-950/50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-chalk-faint">Real players’ lies caught</p>
          <p className="mt-1 text-4xl font-black tracking-tight">
            {firstLive ? pct(firstLive.value) : '—'} <span className="text-chalk-faint">→</span>{' '}
            {liveBig ? pct(liveBig.caught.value) : '—'}
          </p>
          <p className="mt-1 text-xs text-chalk-dim">
            in live play, {names[0]} → {liveBig?.version ?? '—'} ({liveBig ? `${liveBig.caught.n} lies` : ''}). Higher is
            better.
          </p>
        </div>
        <div className="rounded-xl bg-ink-950/50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-chalk-faint">Right on everyday headlines</p>
          <p className="mt-1 text-4xl font-black tracking-tight">{liveOverall ? pct(liveOverall.value) : '—'}</p>
          <p className="mt-1 text-xs text-chalk-dim">
            {live?.name ?? 'live version'}, on half true headlines, half AI-written lies. It should stay steady.
          </p>
        </div>
      </div>

      {/* 1 ------------------------------------------------------------------- */}
      <Question n={1} title="Is it catching more real players’ lies?" good="higher is better">
        <p>
          Every judge-approved lie played against each version during the game, caught or not. This is the most
          direct answer: how often the version people actually played against caught them.
        </p>
        <p className="text-xs text-chalk-faint">
          Different versions faced different players and days, and a brand-new version has few rounds yet — its bar
          firms up as people play.
        </p>
      </Question>
      {tables ? (
        <SimpleTable
          head={['Version', 'Lies caught in live play']}
          rows={names.map((n) => [n, ciText(data.live.find((x) => x.version === n)?.caught)])}
        />
      ) : (
        <div className="mt-3">
          <LiveChart data={data} names={names} />
        </div>
      )}

      {/* 2 ------------------------------------------------------------------- */}
      <Question n={2} title="Did it learn the tricks that beat earlier versions?" good="higher is better">
        <p>
          Lies players snuck past, on headlines no version trained on. They are grouped by which version they
          fooled when played, and each group only scores the <em>other</em> versions — scoring a version on lies
          chosen because it missed them would be rigged.
        </p>
        <p className="text-xs text-chalk-faint">
          These are the hardest lies there are, so the numbers are low by nature. The question is whether newer
          versions catch more than older ones. Small samples: read them as counts.
        </p>
      </Question>
      {tables ? (
        <SimpleTable
          head={['Version', ...names.map((g) => `Lies that fooled ${g}`)]}
          rows={data.verifier.map((v) => [
            v.name,
            ...names.map((g) => (g === v.name ? 'n/a (picked against it)' : (v.benchmark?.by_fooled?.[g] ? count(v.benchmark.by_fooled[g]) : '—'))),
          ])}
        />
      ) : (
        <div className="mt-3">
          <FairChart data={data} names={names} />
        </div>
      )}

      {/* 3 ------------------------------------------------------------------- */}
      <Question n={3} title="Did it get worse at everyday headlines?" good="flat is good">
        <p>
          Accuracy on a mix of half true headlines and half AI-written lies, none picked against any version. Training
          on the hard cases often breaks what a model already knew; a steady bar means it didn’t.
        </p>
      </Question>
      {tables ? (
        <SimpleTable
          head={['Version', 'Right on everyday headlines']}
          rows={data.verifier.map((v) => {
            const o = overall(v);
            return [v.name, o ? `${pct(o.value)} [${pct(o.lo)}–${pct(o.hi)}]` : '—'];
          })}
        />
      ) : (
        <div className="mt-3">
          <OverallChart versions={data.verifier.filter((v) => v.benchmark)} />
        </div>
      )}

      {pending.length > 0 && (
        <p className="mt-3 text-xs text-chalk-faint">
          Being re-measured on the same tests as the live version: {pending.join(', ')}.
        </p>
      )}

      <details className="mt-8">
        <summary className="cursor-pointer font-bold">Details: the two parts of “everyday accuracy”</summary>
        <p className="mt-2 text-sm text-chalk-dim">
          {data.verifier[0]?.benchmark?.lies_caught.n ?? '…'} AI-written lies and {data.verifier[0]?.benchmark?.true_flagged.n ?? '…'} true
          headlines, all on held-out headlines. A version can catch more lies by flagging more of everything, so read
          the two bars together.
        </p>
        {tables ? (
          <SimpleTable
            head={['Version', 'AI-written lies caught', 'True headlines wrongly flagged']}
            rows={data.verifier.map((v) => [v.name, ciText(v.benchmark?.lies_caught), ciText(v.benchmark?.true_flagged)])}
          />
        ) : (
          <div className="mt-3">
            <BreakdownChart versions={data.verifier} />
          </div>
        )}
      </details>

      <details className="mt-4">
        <summary className="cursor-pointer font-bold">The first-glance meter (the bar while you type)</summary>
        <p className="mt-2 text-sm text-chalk-dim">
          A quick preview: the fact-checker reading your edit against one passage from the source article. Scored on
          its own held-out headlines, so don’t compare these numbers with the charts above.
        </p>
        {tables ? (
          <SimpleTable
            head={['Version', 'AI-written lies flagged', 'True headlines wrongly flagged']}
            rows={data.meter.map((v) => [v.name, ciText(v.benchmark?.lies_caught), ciText(v.benchmark?.true_flagged)])}
          />
        ) : (
          <div className="mt-3">
            <BreakdownChart versions={data.meter} />
          </div>
        )}
      </details>
    </section>
  );
}

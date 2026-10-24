'use client';

/**
 * The AI scorecard on /learn: how good the fact-checker and the meter are now,
 * and how each version compares with the last on the same fixed benchmark.
 * Colour follows the entity (lib/viz.ts): your lies blue, machine-written lies
 * orange, true headlines aqua. Whiskers are 95% bootstrap intervals.
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
const err = (c?: CI | null) => (c && c.value !== null ? [c.value - (c.lo ?? c.value), (c.hi ?? c.value) - c.value] : [0, 0]);
const ciText = (c?: CI | null) => (!c || c.value === null ? '—' : `${pct(c.value)} [${pct(c.lo)}–${pct(c.hi)}], n=${c.n}`);

function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-3 py-2 text-xs">
      <p className="font-semibold text-chalk">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="mt-1 flex items-center gap-2 text-chalk-dim">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} aria-hidden />
          {p.name}: <span className="num text-chalk">{pct(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

function Headline({ label, value, sub, color }: { label: string; value: CI | undefined; sub: string; color: string }) {
  return (
    <div className="rounded-xl bg-ink-950/50 p-4">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-chalk-faint">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} aria-hidden />
        {label}
      </p>
      <p className="mt-1 text-4xl font-black tracking-tight">{value?.value != null ? pct(value.value) : '—'}</p>
      <p className="mt-1 text-xs text-chalk-dim">
        {value?.value != null ? `95% range ${pct(value.lo)}–${pct(value.hi)} · ` : ''}
        {sub}
      </p>
    </div>
  );
}

function VersionChart({ rows, withLive }: { rows: any[]; withLive: boolean }) {
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows} barGap={2} margin={{ top: 22, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Legend {...LEGEND} />
          <Bar name="Machine-written lies caught" dataKey="machine" fill={SERIES.machine} radius={END}>
            <ErrorBar dataKey="machineErr" width={5} stroke={INK.secondary} />
            <LabelList dataKey="machine" position="top" offset={12} formatter={(v: number) => pct(v)} fill={INK.secondary} fontSize={11} />
          </Bar>
          {withLive && (
            <Bar name="Your lies caught" dataKey="human" fill={SERIES.human} radius={END}>
              <ErrorBar dataKey="humanErr" width={5} stroke={INK.secondary} />
              <LabelList dataKey="human" position="top" offset={12} formatter={(v: number) => pct(v)} fill={INK.secondary} fontSize={11} />
            </Bar>
          )}
          <Bar name="True headlines wrongly flagged" dataKey="truth" fill={SERIES.truth} radius={END}>
            <ErrorBar dataKey="truthErr" width={5} stroke={INK.secondary} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function rowsFor(versions: LearningVersion[], live?: LearningSummary['live']) {
  return versions.map((v) => {
    const l = live?.find((x) => x.version === v.name)?.caught;
    return {
      name: v.name,
      machine: v.benchmark?.lies_caught.value ?? null,
      machineErr: err(v.benchmark?.lies_caught),
      truth: v.benchmark?.true_flagged.value ?? null,
      truthErr: err(v.benchmark?.true_flagged),
      human: l?.value ?? null,
      humanErr: err(l),
    };
  });
}

function Table({ versions, live }: { versions: LearningVersion[]; live?: LearningSummary['live'] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-chalk-faint">
            <th className="py-2 font-medium">Version</th>
            <th className="py-2 font-medium">Machine-written lies caught</th>
            {live && <th className="py-2 font-medium">Your lies caught</th>}
            <th className="py-2 font-medium">True headlines flagged</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.name} className="border-t border-ink-800">
              <td className="py-2 font-semibold">
                {v.name}
                {v.is_current && <span className="ml-2 text-xs text-truth">live</span>}
              </td>
              <td className="num py-2 text-chalk-dim">{ciText(v.benchmark?.lies_caught)}</td>
              {live && <td className="num py-2 text-chalk-dim">{ciText(live.find((x) => x.version === v.name)?.caught)}</td>}
              <td className="num py-2 text-chalk-dim">{ciText(v.benchmark?.true_flagged)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Scorecard({ data }: { data: LearningSummary }) {
  const [tables, setTables] = useState(false);
  const live = data.verifier.find((v) => v.is_current);
  const liveNow = data.live.find((x) => x.version === live?.name)?.caught;
  const retrained = data.verifier.filter((v) => v.train_data === 'human').length > 0;
  const first = data.meter[0]?.benchmark;
  const now = data.meter.find((m) => m.is_current)?.benchmark;

  return (
    <section className="panel mt-8 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="label">The AI’s scorecard</p>
          <h2 className="mt-1 text-xl font-bold">How good is it — and is it getting better?</h2>
        </div>
        <button type="button" className="chip shrink-0" onClick={() => setTables((t) => !t)}>
          {tables ? 'Show charts' : 'Show tables'}
        </button>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Headline
          label="Machine-written lies it catches"
          value={live?.benchmark?.lies_caught}
          sub={`${live?.benchmark?.lies_caught.n ?? 0} AI-written fakes on held-out headlines`}
          color={SERIES.machine}
        />
        <Headline
          label="Your lies it catches"
          value={liveNow}
          sub={`${liveNow?.n ?? 0} judge-approved lies played against ${live?.name ?? 'it'}`}
          color={SERIES.human}
        />
      </div>
      {live?.benchmark?.lies_caught.value != null && liveNow?.value != null && (
        <p className="mt-3 text-sm text-chalk-dim">
          {liveNow.value < live.benchmark.lies_caught.value ? (
            <>
              People fool the fact-checker far more often than AI-written lies do — that gap is exactly what this
              game collects. It wrongly flags {pct(live.benchmark.true_flagged.value)} of true headlines.
            </>
          ) : (
            <>Right now it catches your lies about as well as AI-written ones.</>
          )}
        </p>
      )}

      <h3 className="mt-6 font-bold">The fact-checker, version by version</h3>
      <p className="mt-1 text-sm text-chalk-dim">
        Every version is scored on the same held-out headlines no version trains on.{' '}
        {retrained
          ? 'Each patch day adds a version trained on your approved lies.'
          : 'No patch day yet: it is still the off-the-shelf v0. The first retrain comes once enough of your lies are approved — this chart will show whether it improved, including if it didn’t.'}
      </p>
      <div className="mt-3">
        {tables ? <Table versions={data.verifier} live={data.live} /> : <VersionChart rows={rowsFor(data.verifier, data.live)} withLive />}
      </div>

      <h3 className="mt-6 font-bold">The first-glance meter, version by version</h3>
      <p className="mt-1 text-sm text-chalk-dim">
        {first && now
          ? `From its first version to the live one, it went from catching ${pct(first.lies_caught.value)} of machine-written lies to ${pct(now.lies_caught.value)}, and from wrongly flagging ${pct(first.true_flagged.value)} of true headlines to ${pct(now.true_flagged.value)}.`
          : 'Scored on its own held-out headlines.'}
      </p>
      <div className="mt-3">
        {tables ? <Table versions={data.meter} /> : <VersionChart rows={rowsFor(data.meter)} withLive={false} />}
      </div>
    </section>
  );
}

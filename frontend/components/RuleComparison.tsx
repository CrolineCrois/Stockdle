'use client';

/**
 * "How it decides": the evidence-combining rule comparison (data/eval/
 * rule_comparison.json, copied to public/). Same models, same retrieved
 * evidence, three rules for turning per-passage scores into one verdict.
 */

import { useEffect, useState } from 'react';

import { pct } from '@/lib/viz';

type Cell = { value: number; lo: number; hi: number };
type Doc = {
  rules: Record<string, string>;
  chosen: string;
  note: string;
  sets: Record<string, { n: number; models: Record<string, Record<string, Cell>> }>;
};

const RULES: [string, string][] = [
  ['strongest', 'A · strongest wins'],
  ['contradiction', 'B · any contradiction'],
  ['source', 'C · source contradiction'],
];

export default function RuleComparison() {
  const [doc, setDoc] = useState<Doc | null>(null);
  useEffect(() => {
    fetch('/rule_comparison.json')
      .then((r) => (r.ok ? r.json() : null))
      .then(setDoc)
      .catch(() => undefined);
  }, []);
  if (!doc) return null;
  const sets = Object.entries(doc.sets);
  const models = Object.keys(sets[0]?.[1].models ?? {});

  return (
    <section className="panel p-4 sm:p-5 lg:col-span-2">
      <p className="label">How it decides</p>
      <h2 className="mt-1 text-lg font-bold leading-snug">
        A flaw in how it combined evidence — found from player lies, then fixed
      </h2>
      <p className="mt-1 text-sm text-chalk-dim">
        The fact-checker reads three passages and must turn them into one verdict. The original rule (A) let
        the strongest <em>support</em> outvote a contradiction. Player lies change one fact and keep the rest
        true, so another article “supported” the unchanged part and outvoted the source article that
        contradicted the lie. Rule C lets a confident contradiction from the claim’s own source win.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-chalk-faint">
              <th className="py-2 pr-3 font-medium">Model · rule</th>
              {sets.map(([name, s]) => (
                <th key={name} className="py-2 pr-3 font-medium">
                  {name.replace(' (held out)', '')} <span className="text-chalk-faint">(n={s.n})</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {models.flatMap((m) =>
              RULES.map(([rule, label]) => {
                const chosen = m === 'v2-human' && rule === doc.chosen;
                const before = m === 'v1-human' && rule === 'strongest';
                return (
                  <tr key={m + rule} className={`border-t border-ink-800 ${chosen ? 'bg-accent/10' : ''}`}>
                    <td className="py-2 pr-3">
                      <span className="num font-semibold">{m}</span> <span className="text-chalk-dim">· {label}</span>
                      {chosen && <span className="ml-2 text-xs text-accent">live now</span>}
                      {before && <span className="ml-2 text-xs text-chalk-faint">live before</span>}
                    </td>
                    {sets.map(([name, s]) => {
                      const c = s.models[m]?.[rule];
                      return (
                        <td key={name} className="num py-2 pr-3 text-chalk-dim">
                          {c ? (
                            <>
                              <span className="text-chalk">{pct(c.value)}</span> [{pct(c.lo)}–{pct(c.hi)}]
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              }),
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-chalk-faint">
        Share of each set called <em>refuted</em>: higher is better for lies, lower is better for true headlines.{' '}
        {doc.note}
      </p>
    </section>
  );
}

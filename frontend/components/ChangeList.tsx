'use client';

/** An edit as readable word changes: "a → b", "−deleted", "+inserted". */

import type { WordChange } from '@/lib/api';

export default function ChangeList({ changes, className = '' }: { changes: WordChange[]; className?: string }) {
  return (
    <span className={`inline-flex flex-wrap gap-x-3 gap-y-1 ${className}`}>
      {changes.map((c, i) => (
        <span key={i}>
          {c.op === 'replace' && (
            <>
              <span className="text-chalk-faint line-through">{c.before}</span>
              {' → '}
              <span className="font-semibold text-accent">{c.after}</span>
            </>
          )}
          {c.op === 'delete' && (
            <span className="text-chalk-faint">
              −<span className="line-through">{c.before}</span>
            </span>
          )}
          {c.op === 'insert' && <span className="font-semibold text-accent">+{c.after}</span>}
        </span>
      ))}
    </span>
  );
}

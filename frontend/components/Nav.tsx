'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const LINKS = [
  { href: '/', label: 'Play' },
  { href: '/board', label: 'Board' },
  { href: '/learn', label: 'How it learns' },
  { href: '/lab', label: 'Lab' },
];

export default function Nav({ right }: { right?: React.ReactNode }) {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-ink-800/80 bg-ink-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/" className="group flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-you text-sm font-black text-ink-950">
            S
          </span>
          <span className="text-sm font-bold tracking-[0.2em] text-chalk">SNEAK IT PAST</span>
        </Link>
        <nav className="flex items-center gap-1">
          {LINKS.map((l) => {
            const active = l.href === '/' ? path === '/' : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  active
                    ? 'bg-ink-800 font-semibold text-chalk'
                    : 'text-chalk-dim hover:bg-ink-800/60 hover:text-chalk'
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">{right}</div>
      </div>
    </header>
  );
}

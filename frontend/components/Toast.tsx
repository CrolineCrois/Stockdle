'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect } from 'react';

export interface ToastMessage {
  id: number;
  title: string;
  body?: string;
  tone?: 'ai' | 'info' | 'warn';
}

const TONE = {
  ai: 'border-robot/50 bg-robot/10 text-robot',
  info: 'border-ink-600 bg-ink-800/90 text-chalk',
  warn: 'border-danger/50 bg-danger/10 text-danger',
} as const;

export default function Toasts({
  messages,
  onExpire,
  ttl = 5200,
}: {
  messages: ToastMessage[];
  onExpire: (id: number) => void;
  ttl?: number;
}) {
  useEffect(() => {
    const timers = messages.map((m) => setTimeout(() => onExpire(m.id), ttl));
    return () => timers.forEach(clearTimeout);
  }, [messages, onExpire, ttl]);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex flex-col items-center gap-2 px-4">
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <motion.div
            key={m.id}
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }}
            transition={{ type: 'spring', stiffness: 380, damping: 28 }}
            className={`pointer-events-auto w-full max-w-md rounded-xl border px-4 py-3 shadow-panel backdrop-blur ${
              TONE[m.tone ?? 'info']
            }`}
          >
            <p className="text-sm font-bold">{m.title}</p>
            {m.body && <p className="mt-0.5 text-xs text-chalk-dim">{m.body}</p>}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

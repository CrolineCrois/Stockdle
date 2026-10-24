'use client';

import { Suspense } from 'react';

import PlayClient from './PlayClient';

export default function PlayPage() {
  return (
    <Suspense
      fallback={
        <div className="grid min-h-dvh place-items-center text-sm text-chalk-dim">
          Loading…
        </div>
      }
    >
      <PlayClient />
    </Suspense>
  );
}

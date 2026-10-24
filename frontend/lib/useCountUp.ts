'use client';

import { useEffect, useState } from 'react';

import { sound } from './sound';

/** Animate 0 -> target over ``ms``, ticking a sound every few frames. */
export function useCountUp(target: number, ms = 900): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (target <= 0) {
      setValue(target);
      return;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(target);
      return;
    }
    const t0 = performance.now();
    let frame = 0;
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms);
      const eased = 1 - (1 - p) ** 3;
      setValue(Math.round(target * eased));
      frame += 1;
      if (frame % 4 === 0 && p < 1) sound.score(frame / 4);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return value;
}

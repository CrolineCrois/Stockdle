'use client';

/** Canvas confetti for bullseyes. Self-cleaning, no dependencies. */

import { useEffect, useRef } from 'react';

const COLORS = ['#f0b429', '#0ca30c', '#3987e5', '#d55181', '#f8fafc'];

interface Bit {
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  vr: number;
  size: number;
  color: string;
  life: number;
}

export default function Confetti({ fire }: { fire: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const bits = useRef<Bit[]>([]);
  const raf = useRef(0);

  useEffect(() => {
    if (!fire) return;
    const canvas = ref.current;
    if (!canvas) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const w = window.innerWidth;
    const h = window.innerHeight;
    bits.current = Array.from({ length: 150 }, () => {
      const angle = -Math.PI / 2 + (Math.random() - 0.5) * 1.5;
      const speed = 7 + Math.random() * 11;
      return {
        x: w * (0.2 + Math.random() * 0.6),
        y: h * 0.62,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        rot: Math.random() * Math.PI,
        vr: (Math.random() - 0.5) * 0.4,
        size: 5 + Math.random() * 7,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
        life: 1,
      };
    });

    const tick = () => {
      ctx.clearRect(0, 0, w, h);
      let alive = false;
      for (const b of bits.current) {
        b.vy += 0.34;              // gravity
        b.vx *= 0.995;             // drag
        b.x += b.vx;
        b.y += b.vy;
        b.rot += b.vr;
        b.life -= 0.0085;
        if (b.life <= 0 || b.y > h + 40) continue;
        alive = true;
        ctx.save();
        ctx.globalAlpha = Math.max(0, Math.min(1, b.life));
        ctx.translate(b.x, b.y);
        ctx.rotate(b.rot);
        ctx.fillStyle = b.color;
        ctx.fillRect(-b.size / 2, -b.size / 4, b.size, b.size / 2);
        ctx.restore();
      }
      if (alive) {
        raf.current = requestAnimationFrame(tick);
      } else {
        ctx.clearRect(0, 0, w, h);
      }
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [fire]);

  return (
    <canvas
      ref={ref}
      aria-hidden
      className="pointer-events-none fixed inset-0 z-50 h-dvh w-screen"
    />
  );
}

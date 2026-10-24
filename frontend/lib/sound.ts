/**
 * Tiny Web Audio sound kit — every sound is synthesised, so there are no
 * asset downloads and nothing to license. The context is created lazily on the
 * first gesture because browsers refuse to start one before user interaction.
 */

const MUTE_KEY = 'tape.muted';

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let muted = false;
let lastTick = 0;

function ensure(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!ctx) {
    const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
    master = ctx.createGain();
    master.gain.value = 0.3;
    master.connect(ctx.destination);
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

function tone(
  freq: number,
  duration: number,
  {
    type = 'sine',
    gain = 0.5,
    delay = 0,
    sweepTo,
  }: { type?: OscillatorType; gain?: number; delay?: number; sweepTo?: number } = {},
) {
  const audio = ensure();
  if (!audio || !master || muted) return;
  const t0 = audio.currentTime + delay;
  const osc = audio.createOscillator();
  const env = audio.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (sweepTo) osc.frequency.exponentialRampToValueAtTime(Math.max(sweepTo, 1), t0 + duration);
  // Short attack, exponential decay — reads as "tick" rather than "beep".
  env.gain.setValueAtTime(0.0001, t0);
  env.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
  env.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(env);
  env.connect(master);
  osc.start(t0);
  osc.stop(t0 + duration + 0.02);
}

export const sound = {
  init: () => void ensure(),

  isMuted: () => muted,

  setMuted(next: boolean) {
    muted = next;
    try {
      window.localStorage.setItem(MUTE_KEY, next ? '1' : '0');
    } catch {
      /* private mode */
    }
  },

  restore() {
    try {
      muted = window.localStorage.getItem(MUTE_KEY) === '1';
    } catch {
      muted = false;
    }
    return muted;
  },

  /** Pitch rises with the height of the line, so drawing *sounds* like the shape. */
  draw(value: number) {
    const now = performance.now();
    if (now - lastTick < 38) return;
    lastTick = now;
    tone(220 + value * 520, 0.05, { type: 'triangle', gain: 0.12 });
  },

  reveal() {
    tone(330, 0.9, { type: 'sine', gain: 0.22, sweepTo: 660 });
    tone(165, 0.9, { type: 'sine', gain: 0.1, sweepTo: 330 });
  },

  ghost() {
    tone(520, 0.18, { type: 'sine', gain: 0.1 });
    tone(690, 0.2, { type: 'sine', gain: 0.08, delay: 0.09 });
  },

  score(points: number) {
    tone(440 + Math.min(points, 120) * 2.6, 0.12, { type: 'square', gain: 0.1 });
  },

  bullseye() {
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
      tone(f, 0.42, { type: 'triangle', gain: 0.26, delay: i * 0.085 }),
    );
  },

  fail() {
    tone(200, 0.34, { type: 'sawtooth', gain: 0.14, sweepTo: 90 });
  },

  tick() {
    tone(880, 0.05, { type: 'square', gain: 0.07 });
  },
};

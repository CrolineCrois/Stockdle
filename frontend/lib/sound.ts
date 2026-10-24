/**
 * Tiny Web Audio sound kit — every sound is synthesised, so there are no
 * asset downloads and nothing to license. The context is created lazily on the
 * first gesture because browsers refuse to start one before user interaction.
 */

const MUTE_KEY = 'sip.muted';

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

  /** A soft key click while editing. Throttled so fast typing doesn't buzz. */
  key() {
    const now = performance.now();
    if (now - lastTick < 45) return;
    lastTick = now;
    tone(1400 + Math.random() * 300, 0.025, { type: 'triangle', gain: 0.05 });
  },

  /** Got past the detector. */
  sneak() {
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
      tone(f, 0.4, { type: 'triangle', gain: 0.24, delay: i * 0.08 }),
    );
  },

  /** Points counting up. */
  score(step: number) {
    tone(440 + Math.min(step, 40) * 22, 0.08, { type: 'square', gain: 0.06 });
  },

  caught() {
    tone(200, 0.4, { type: 'sawtooth', gain: 0.15, sweepTo: 80 });
  },

  invalid() {
    tone(330, 0.16, { type: 'sine', gain: 0.12 });
    tone(262, 0.2, { type: 'sine', gain: 0.12, delay: 0.12 });
  },

  /** Clock tick for the last five seconds. */
  tick() {
    tone(880, 0.05, { type: 'square', gain: 0.07 });
  },
};

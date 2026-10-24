import type { Config } from 'tailwindcss';

/**
 * Dark, high-contrast palette tuned for a projector: deep ink background,
 * one hot accent per actor on the chart (you / truth / crowd / AI) that stays
 * distinguishable at the back of a room and for the common colour-vision
 * deficiencies — the four differ in lightness as well as hue.
 */
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#05070f', 900: '#0b1020', 800: '#121a31', 700: '#1c2742', 600: '#2b3a5c' },
        chalk: { DEFAULT: '#e8edf7', dim: '#94a3c4', faint: '#5a6a8c' },
        // Chart series — validated; see lib/palette.ts for the report.
        you: '#c98500',       // the player's line
        truth: '#008300',     // what actually happened
        crowd: '#d55181',     // the crowd mean
        robot: '#3987e5',     // the AI
        accent: '#f0b429',    // UI chrome only (buttons, big numbers)
        danger: '#d03b3b',
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Inter', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 40px -10px rgba(240, 180, 41, 0.42)',
        panel: '0 20px 60px -20px rgba(0, 0, 0, 0.8)',
      },
      keyframes: {
        shake: {
          '0%, 100%': { transform: 'translate3d(0,0,0)' },
          '20%': { transform: 'translate3d(-8px,3px,0)' },
          '40%': { transform: 'translate3d(7px,-4px,0)' },
          '60%': { transform: 'translate3d(-5px,-2px,0)' },
          '80%': { transform: 'translate3d(4px,3px,0)' },
        },
        riseIn: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        pulseRing: {
          '0%': { boxShadow: '0 0 0 0 rgba(240,180,41,0.5)' },
          '100%': { boxShadow: '0 0 0 22px rgba(240,180,41,0)' },
        },
      },
      animation: {
        shake: 'shake 0.5s cubic-bezier(.36,.07,.19,.97) both',
        riseIn: 'riseIn 0.35s ease-out both',
        pulseRing: 'pulseRing 1.1s ease-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;

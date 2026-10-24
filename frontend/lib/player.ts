/** Display-name-only identity, kept in localStorage and mirrored server-side. */

import { api, type PlayerInfo } from './api';

const KEY = 'tape.player';

export interface StoredPlayer {
  player_id: string;
  name: string;
}

export function readPlayer(): StoredPlayer | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredPlayer;
    return parsed?.player_id && parsed?.name ? parsed : null;
  } catch {
    return null;
  }
}

export function writePlayer(player: StoredPlayer): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(player));
  } catch {
    /* private mode — the session still works, it just will not persist */
  }
}

export function clearPlayer(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Register (or rename) with the backend and persist whatever it returns. */
export async function signIn(name: string): Promise<PlayerInfo> {
  const existing = readPlayer();
  const info = await api.upsertPlayer(name.trim(), existing?.player_id ?? null);
  writePlayer({ player_id: info.player_id, name: info.name });
  return info;
}

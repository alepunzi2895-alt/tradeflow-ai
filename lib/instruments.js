// Registro strumenti lato server: stessa fonte del browser (public/instruments.json) e degli
// script Python. Import JSON come lib/strategy-registry.js (tracciato dal bundler Vercel).
import registry from '../public/instruments.json' with {type:'json'};

export const INSTRUMENTS = registry.instruments;
const BY_ID = new Map(INSTRUMENTS.map(i => [i.id, i]));
const ALIASES = { SILVER: 'XAG', GOLD: 'XAU', DJI: 'US30' };

export function instrument(id) {
  const k = String(id || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  return BY_ID.get(ALIASES[k] || k) || null;
}
export const isCore = id => !!instrument(id)?.core;

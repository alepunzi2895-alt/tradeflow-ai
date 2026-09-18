import registry from '../data/strategy_registry.json' with {type:'json'};
import blocks from '../data/hard_blocks.json' with {type:'json'};
export function registrySnapshot() {
  return {version:registry.version,strategies:Object.fromEntries(Object.entries(registry.strategies).map(([id,s])=>[id,{...s,...(blocks.blocked[id]?{status:'blocked',...blocks.blocked[id]}:{})}]))};
}

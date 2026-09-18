"""Immutable startup snapshot: execution and UI share configuration and block state."""
import json
from pathlib import Path

def registry_snapshot():
    folder=Path(__file__).resolve().parent.parent/'data'
    registry=json.loads((folder/'strategy_registry.json').read_text(encoding='utf-8'))
    blocks=json.loads((folder/'hard_blocks.json').read_text(encoding='utf-8'))['blocked']
    for key,item in registry['strategies'].items():
        if key in blocks:
            item.update(status='blocked',**blocks[key])
    return registry

SNAPSHOT=registry_snapshot()

def enabled(strategy_id):
    return SNAPSHOT['strategies'].get(strategy_id,{}).get('status')=='eligible'

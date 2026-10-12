"""Install only a tiny bridge into shared equipment; preserve peer preimage."""
import hashlib
from pathlib import Path

target=Path('C:/Users/lucys/Documents/Codex/2026-08-25/yo/work/commons-spark-link/integrations/shared_equipment/services.py')
source=target.read_text(encoding='utf-8')
old_hash=hashlib.sha256(target.read_bytes()).hexdigest()
backup=Path('runtime-preimage-'+old_hash+'.py')
if not backup.exists():backup.write_bytes(target.read_bytes())
if 'def _uncoordinated_call' not in source:
    marker='    def tools(self, **_kwargs) -> list[dict]:\n        return TOOLS.copy()'
    if source.count(marker)!=1:raise RuntimeError('tools preimage moved; reread exact bridge point')
    bridge='''    def _collision_catalog(self):
        # Shared remote authority; every peer uses the same direct credential road.
        import sys
        collision_path = "C:/Users/lucys/Documents/Codex/2026-10-08/ch/work/collision-coordination-20261012"
        if collision_path not in sys.path:
            sys.path.insert(0, collision_path)
        from runtime_adapter import catalog
        return catalog(self)

    def tools(self, **_kwargs) -> list[dict]:
        return list(self._collision_catalog().tools())

    def _uncoordinated_tools(self, **_kwargs) -> list[dict]:
        return TOOLS.copy()'''
    source=source.replace(marker,bridge,1)
    marker='    def call(self, name: str, arguments: dict) -> dict:'
    if source.count(marker)!=1:raise RuntimeError('call preimage moved; reread exact bridge point')
    replacement='''    def call(self, name: str, arguments: dict) -> dict:
        return self._collision_catalog().call(name, arguments)

    def _uncoordinated_call(self, name: str, arguments: dict) -> dict:'''
    source=source.replace(marker,replacement,1)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=old_hash:raise RuntimeError('concurrent source change; reread before install')
    target.write_text(source,encoding='utf-8')
print('installed_remote_coordination_bridge preimage='+old_hash+' current='+hashlib.sha256(target.read_bytes()).hexdigest())

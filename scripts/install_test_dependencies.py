"""Install test component requirements from the installed HA's own manifests."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ha = importlib.util.find_spec("homeassistant")
assert ha is not None and ha.origin is not None
components = Path(ha.origin).parent / "components"
manifest = json.loads(Path("custom_components/feiniu_music/manifest.json").read_text())
requirements = set(manifest["requirements"])
pending = [*manifest["dependencies"], "dlna_dmr"]
visited: set[str] = set()
while pending:
    domain = pending.pop()
    if domain in visited:
        continue
    visited.add(domain)
    component = json.loads((components / domain / "manifest.json").read_text())
    requirements.update(component.get("requirements", []))
    pending.extend(component.get("dependencies", []))

subprocess.run([sys.executable, "-m", "pip", "install", *sorted(requirements)], check=True)

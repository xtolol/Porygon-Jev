import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from showdown_state_tracer.models import DecisionSnapshot

class Telemetry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
    def write(
        self,
        snapshot: DecisionSnapshot,) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": asdict(snapshot),
        }
        
        with self.path.open("a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")
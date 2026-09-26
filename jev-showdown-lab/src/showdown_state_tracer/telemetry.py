from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from showdown_state_tracer.models import DecisionRecord


class Telemetry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def write(
        self,
        decision_record: DecisionRecord,
    ) -> None:
        payload = {
            "schema_version": 5,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            **asdict(decision_record),
        }

        with self.path.open(
            "a",
            encoding="utf-8",
        ) as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
            )
            file.write("\n")

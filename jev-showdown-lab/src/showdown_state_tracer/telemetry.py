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

    # Parameters: decision_record holds the chosen action and annotated state.
    # Purpose: persist the decision with its versioned telemetry envelope.
    # Returns: None after appending a JSON record.
    # Pipeline: records the Jev input context and outcome after choosing an order.
    def write(
        self,
        decision_record: DecisionRecord,
    ) -> None:
        payload = {
            "schema_version": 9,
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

"""Look up bundled Showdown descriptions without Node or network access."""

from functools import lru_cache
from importlib.resources import files
import json
import re
import warnings


@lru_cache(maxsize=1)
def _load_move_descriptions() -> dict[str, str]:
    """Read and validate the packaged Gen 9 lookup once per process."""
    try:
        resource = files("showdown_state_tracer").joinpath(
            "data", "move_descriptions_gen9.json"
        )
        data = json.loads(resource.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1
            or type(data.get("generation")) is not int
            or data["generation"] != 9
            or data.get("language") != "en"
            or not isinstance(data.get("showdown_revision"), str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", data["showdown_revision"])
            or not isinstance(data.get("moves"), dict)
            or not data["moves"]
            or not all(
                isinstance(move_id, str)
                and re.fullmatch(r"[a-z0-9]+", move_id)
                and isinstance(description, str)
                and description.strip()
                for move_id, description in data["moves"].items()
            )
        ):
            raise ValueError("Invalid Gen 9 move-description resource")
        return data["moves"]
    except (OSError, ValueError) as error:
        warnings.warn(
            f"Move descriptions unavailable; continuing without them: {error}",
            RuntimeWarning,
            stacklevel=2,
        )
        return {}


def get_move_short_description(move_id: str, generation: int) -> str | None:
    """Return English mechanics text for a canonical Gen 9 move ID, if present."""
    if generation != 9:
        return None
    desc = _load_move_descriptions().get(move_id)
    if desc is None:
        print(
            f"Warning: no Gen 9 description found for move '{move_id}'; ")
    return desc

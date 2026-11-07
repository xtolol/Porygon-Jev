"""Look up bundled Gen 9 descriptions for known abilities and held items."""

from functools import lru_cache
from importlib.resources import files
import json
import re
from typing import Literal
import warnings

from poke_env.data import to_id_str


DescriptionKind = Literal["abilities", "items"]
RESOURCE_NAMES: dict[DescriptionKind, str] = {
    "abilities": "ability_descriptions_gen9.json",
    "items": "item_descriptions_gen9.json",
}


@lru_cache(maxsize=2)
def _load_descriptions(kind: DescriptionKind) -> dict[str, str]:
    """Cache each resource independently, including an unavailable result."""
    try:
        resource = files("showdown_state_tracer").joinpath("data", RESOURCE_NAMES[kind])
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
            or not isinstance(data.get(kind), dict)
            or not data[kind]
            or not all(
                isinstance(identifier, str)
                and re.fullmatch(r"[a-z0-9]+", identifier)
                and isinstance(description, str)
                and description.strip()
                for identifier, description in data[kind].items()
            )
        ):
            raise ValueError(f"Invalid Gen 9 {kind} description resource")
        return data[kind]
    except (OSError, ValueError) as error:
        warnings.warn(
            f"Gen 9 {kind} descriptions unavailable; continuing without them: {error}",
            RuntimeWarning,
            stacklevel=2,
        )
        return {}


def _get_description(
    identifier: str | None, generation: int, kind: DescriptionKind,
) -> str | None:
    if generation != 9 or not identifier:
        return None
    canonical_id = to_id_str(identifier)
    if not canonical_id or (kind == "items" and canonical_id == "unknownitem"):
        return None
    return _load_descriptions(kind).get(canonical_id)


def get_ability_short_description(ability_id: str | None, generation: int) -> str | None:
    """Return English mechanics text for an already known ability, if available."""
    return _get_description(ability_id, generation, "abilities")


def get_item_short_description(item_id: str | None, generation: int) -> str | None:
    """Return English mechanics text for an already known held item, if available."""
    return _get_description(item_id, generation, "items")

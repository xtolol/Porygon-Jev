"""Load published random-battle sets without making requests during every turn."""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


@dataclass(frozen=True, slots=True)
class RandbatsDataset:
    sets_by_species: dict[str, dict[str, int]]
    retrieved_at: str


class RandbatsDataProvider:
    SUPPORTED_FORMATS = frozenset({"gen9randombattle"})
    BASE_URL = "https://raw.githubusercontent.com/pkmn/randbats/main/data/full"
    MAX_AGE_SECONDS = 24 * 60 * 60

    # Parameters: cache_dir is the optional disk cache; client is an optional HTTP client.
    # Purpose: create the single format-data provider shared by a player's decisions.
    # Returns: an instance with no network work performed yet.
    # Pipeline: the battle entry point owns this provider until shutdown.
    def __init__(
        self, cache_dir: Path | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        cache_root = os.getenv("XDG_CACHE_HOME")
        self._cache_dir = (
            cache_dir if cache_dir is not None else
            (Path(cache_root) if cache_root else Path.home() / ".cache")
            / "porygon-jev" / "randbats"
        )
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None
        self._loaded: dict[str, RandbatsDataset | None] = {}
        self._lock = asyncio.Lock()

    # Parameters: format_id selects a supported battle format and cache file.
    # Purpose: parse a previously downloaded complete-set dataset, when present.
    # Returns: the cached dataset and its download time, or None for invalid data.
    # Pipeline: allows battle decisions to use local data even if refresh fails.
    def _read_cached(self, format_id: str) -> RandbatsDataset | None:
        path = self._cache_dir / f"{format_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("sets"), dict)
                or not isinstance(data.get("retrieved_at"), str)
            ):
                return None
            return RandbatsDataset(data["sets"], data["retrieved_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # Parameters: format_id is an allowlisted Random Battle format.
    # Purpose: fetch complete sampled sets and write an atomic local cache copy.
    # Returns: the newly fetched dataset, or None when the source is unavailable.
    # Pipeline: refreshes the shared data before local species and move filtering.
    async def _download(self, format_id: str) -> RandbatsDataset | None:
        try:
            response = await self._client.get(f"{self.BASE_URL}/{format_id}.json")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not all(
                isinstance(species, str) and isinstance(sets, dict)
                for species, sets in data.items()
            ):
                return None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

        retrieved_at = datetime.now(timezone.utc).isoformat()
        dataset = RandbatsDataset(data, retrieved_at)
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_dir / f"{format_id}.json"
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps({"retrieved_at": retrieved_at, "sets": data}), encoding="utf-8"
            )
            temporary.replace(path)
        except OSError:
            pass  # In-memory data remains usable when disk caching is disabled.
        return dataset

    # Parameters: format_id comes from the public battle format identifier.
    # Purpose: choose fresh cached data, refresh old data, or reuse stale data offline.
    # Returns: a complete-set dataset or None for unsupported/unavailable formats.
    # Pipeline: called before building a decision, never once for each move candidate.
    async def get_format(self, format_id: str | None) -> RandbatsDataset | None:
        if format_id not in self.SUPPORTED_FORMATS:
            return None
        async with self._lock:
            if format_id in self._loaded:
                return self._loaded[format_id]
            cached = self._read_cached(format_id)
            if cached is not None:
                try:
                    age = time.time() - datetime.fromisoformat(
                        cached.retrieved_at
                    ).timestamp()
                    if 0 <= age < self.MAX_AGE_SECONDS:
                        self._loaded[format_id] = cached
                        return cached
                except ValueError:
                    cached = None
            dataset = await self._download(format_id) or cached
            self._loaded[format_id] = dataset
            return dataset

    # Parameters: none.
    # Purpose: release an HTTP client created by this provider.
    # Returns: None after cleanup.
    # Pipeline: runs after battles have finished, alongside Jev client cleanup.
    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

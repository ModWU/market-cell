from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from market_cell.data.sources import CandleBatch, CandleQuery, SourceProfile
from market_cell.models import Candle


class CandleCache(Protocol):
    def load(self, query: CandleQuery, source: SourceProfile) -> CandleBatch | None:
        ...

    def save(self, batch: CandleBatch) -> None:
        ...


class FileSystemCandleCache:
    def __init__(self, root: Path | str = ".market_cell_cache/candles") -> None:
        self.root = Path(root)

    def load(self, query: CandleQuery, source: SourceProfile) -> CandleBatch | None:
        path = self._path_for(query, source)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CandleBatch(
            query=CandleQuery(**payload["query"]),
            candles=[Candle.from_dict(item) for item in payload["candles"]],
            source=SourceProfile(**payload["source"]),
            fetched_at=payload["fetched_at"],
            metadata={**payload.get("metadata", {}), "cache_hit": True, "cache_path": str(path)},
        )

    def save(self, batch: CandleBatch) -> None:
        path = self._path_for(batch.query, batch.source)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": asdict(batch.query),
            "candles": [asdict(candle) for candle in batch.candles],
            "source": asdict(batch.source),
            "fetched_at": batch.fetched_at,
            "metadata": batch.metadata,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path_for(self, query: CandleQuery, source: SourceProfile) -> Path:
        raw = json.dumps(
            {"query": asdict(query), "provider": source.provider},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        symbol = safe_path_part(query.symbol)
        horizon = safe_path_part(query.horizon)
        provider = safe_path_part(source.provider)
        return self.root / provider / symbol / horizon / f"{digest}.json"


def safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower() or "unknown"

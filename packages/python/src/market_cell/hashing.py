import hashlib
import json
from typing import Any


def canonical_json_bytes(data: dict[str, Any]) -> bytes:
    raw = json.dumps(
        data,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return raw.encode("utf-8")


def canonical_json_hash_and_size(data: dict[str, Any]) -> tuple[str, int]:
    raw = canonical_json_bytes(data)
    return hashlib.sha256(raw).hexdigest(), len(raw)


def stable_json_hash(data: dict[str, Any]) -> str:
    content_hash, _ = canonical_json_hash_and_size(data)
    return content_hash

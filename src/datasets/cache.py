from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable, List

from src.config import Config


def cache_file_path(cfg: Config, session_id: str) -> Path:
    """
    Host-side path to the simple dataset cache list (one id per line).
    Lives under ./sessions/<sid>/<cache_filename> **regardless of TMPFS/BIND**.
    """
    return cfg.session_dir(session_id) / cfg.cache_filename


def read_ids(cfg: Config, session_id: str) -> List[str]:
    """
    Return the list of cached dataset IDs (de-duplicated, in order).
    """
    p = cache_file_path(cfg, session_id)
    if not p.exists():
        return []
    # normalize + de-dup while preserving order
    seen = set()
    out: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        ds = line.strip()
        if not ds:
            continue
        if ds not in seen:
            seen.add(ds)
            out.append(ds)
    return out


def is_cached(cfg: Config, session_id: str, ds_id: str) -> bool:
    """True if ds_id is already listed in the cache file."""
    return ds_id in read_ids(cfg, session_id)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp.flush()
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_ids(cfg: Config, session_id: str, ids: Iterable[str]) -> Path:
    """
    Overwrite the cache file with the given ids (de-duplicated, in order).
    Returns the path to the cache file.
    """
    unique: List[str] = []
    seen = set()
    for s in ids:
        s = str(s).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique.append(s)
    p = cache_file_path(cfg, session_id)
    _atomic_write_text(p, "\n".join(unique) + ("\n" if unique else ""))
    return p


def add_id(cfg: Config, session_id: str, ds_id: str) -> Path:
    """
    Append ds_id to the cache (idempotent). Returns the cache file path.
    """
    ids = read_ids(cfg, session_id)
    if ds_id not in ids:
        ids.append(ds_id)
        return write_ids(cfg, session_id, ids)
    return cache_file_path(cfg, session_id)


def clear_cache(cfg: Config, session_id: str) -> Path:
    """
    Clear the cache file by writing an empty list. Returns the cache file path.
    """
    return write_ids(cfg, session_id, [])

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..config import Config


class DatasetStatus:
    """Status values for dataset loading."""
    LOADED = "loaded"
    PENDING = "pending"
    FAILED = "failed"


class DatasetEntry:
    """Represents a dataset entry in the cache."""
    def __init__(self, id: str, status: str = DatasetStatus.PENDING, timestamp: Optional[str] = None):
        self.id = id
        self.status = status
        self.timestamp = timestamp or datetime.utcnow().isoformat() + "Z"
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "status": self.status,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "DatasetEntry":
        return cls(
            id=data["id"],
            status=data.get("status", DatasetStatus.PENDING),
            timestamp=data.get("timestamp")
        )


def cache_file_path(cfg: Config, session_id: str) -> Path:
    """
    Host-side path to the structured dataset cache file (JSON format).
    Lives under ./sessions/<sid>/<cache_filename> **regardless of TMPFS/BIND**.
    """
    return cfg.session_dir(session_id) / cfg.cache_filename


def _read_cache_data(cfg: Config, session_id: str) -> Dict[str, List[Dict[str, str]]]:
    """Read the raw cache data from file."""
    p = cache_file_path(cfg, session_id)
    if not p.exists():
        return {"datasets": []}
    
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        # If file is corrupted or doesn't exist, return empty cache
        return {"datasets": []}


def _write_cache_data(cfg: Config, session_id: str, data: Dict[str, List[Dict[str, str]]]) -> Path:
    """Write the raw cache data to file atomically."""
    p = cache_file_path(cfg, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=p.parent, delete=False) as tmp:
        tmp.write(json_str)
        tmp.flush()
        tmp_path = Path(tmp.name)
    tmp_path.replace(p)
    return p


def read_entries(cfg: Config, session_id: str) -> List[DatasetEntry]:
    """
    Return the list of cached dataset entries (de-duplicated, in order).
    """
    data = _read_cache_data(cfg, session_id)
    seen = set()
    out: List[DatasetEntry] = []
    
    for entry_data in data.get("datasets", []):
        entry = DatasetEntry.from_dict(entry_data)
        if entry.id not in seen:
            seen.add(entry.id)
            out.append(entry)
    
    return out


def read_ids(cfg: Config, session_id: str) -> List[str]:
    """
    Return the list of cached dataset IDs (de-duplicated, in order).
    Backward compatibility function.
    """
    return [entry.id for entry in read_entries(cfg, session_id)]


def read_pending_ids(cfg: Config, session_id: str) -> List[str]:
    """
    Return the list of dataset IDs with PENDING status (de-duplicated, in order).
    This is used by the sync system to only stage datasets that need to be loaded.
    """
    entries = read_entries(cfg, session_id)
    return [entry.id for entry in entries if entry.status == DatasetStatus.PENDING]


def is_cached(cfg: Config, session_id: str, ds_id: str) -> bool:
    """True if ds_id is already listed in the cache file."""
    return ds_id in read_ids(cfg, session_id)


def get_entry_status(cfg: Config, session_id: str, ds_id: str) -> Optional[str]:
    """Get the status of a specific dataset entry, or None if not found."""
    entries = read_entries(cfg, session_id)
    for entry in entries:
        if entry.id == ds_id:
            return entry.status
    return None


def write_entries(cfg: Config, session_id: str, entries: Iterable[DatasetEntry]) -> Path:
    """
    Overwrite the cache file with the given entries (de-duplicated, in order).
    Returns the path to the cache file.
    """
    unique: List[DatasetEntry] = []
    seen = set()
    for entry in entries:
        if not entry.id or entry.id in seen:
            continue
        seen.add(entry.id)
        unique.append(entry)
    
    data = {"datasets": [entry.to_dict() for entry in unique]}
    return _write_cache_data(cfg, session_id, data)


def write_ids(cfg: Config, session_id: str, ids: Iterable[str]) -> Path:
    """
    Overwrite the cache file with the given ids (de-duplicated, in order).
    Backward compatibility function - creates entries with PENDING status.
    Returns the path to the cache file.
    """
    entries = [DatasetEntry(id=str(id).strip()) for id in ids if str(id).strip()]
    return write_entries(cfg, session_id, entries)


def add_entry(cfg: Config, session_id: str, ds_id: str, status: str = DatasetStatus.PENDING) -> Path:
    """
    Add or update a dataset entry in the cache (idempotent). Returns the cache file path.
    """
    entries = read_entries(cfg, session_id)
    
    # Check if entry already exists
    existing_entry = None
    for entry in entries:
        if entry.id == ds_id:
            existing_entry = entry
            break
    
    if existing_entry:
        # Update existing entry
        existing_entry.status = status
        existing_entry.timestamp = datetime.utcnow().isoformat() + "Z"
    else:
        # Add new entry
        entries.append(DatasetEntry(id=ds_id, status=status))
    
    return write_entries(cfg, session_id, entries)


def add_id(cfg: Config, session_id: str, ds_id: str) -> Path:
    """
    Append ds_id to the cache (idempotent). Returns the cache file path.
    Backward compatibility function - creates entry with PENDING status.
    """
    return add_entry(cfg, session_id, ds_id, DatasetStatus.PENDING)


def update_entry_status(cfg: Config, session_id: str, ds_id: str, status: str) -> Path:
    """
    Update the status of an existing dataset entry. Returns the cache file path.
    """
    return add_entry(cfg, session_id, ds_id, status)


def clear_cache(cfg: Config, session_id: str) -> Path:
    """
    Clear the cache file by writing an empty list. Returns the cache file path.
    """
    return write_entries(cfg, session_id, [])

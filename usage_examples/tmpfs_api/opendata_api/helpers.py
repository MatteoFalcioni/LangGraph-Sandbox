from client import BolognaOpenData
from typing import Any, Dict, List, Optional
import re, html
import Path

# --------------
# list datasets
# --------------
async def list_catalog(
    client: BolognaOpenData,
    q: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, str]]:
    """
    List datasets

    Returns a list of dicts: {'dataset_id': str, 'title': str}

    Args:
        q: optional free-text search.
        limit: number of datasets to return (API max ~100).
    """

    catalog = await client.list_datasets(q=q, limit=limit)

    out: List[Dict[str, str]] = []
    for item in catalog.get("results", []):
        dsid = item.get("dataset_id", "")
        metas = item.get("metas", {})
        default_meta = metas.get("default", {}) if isinstance(metas.get("default", {}), dict) else {}
        title = default_meta.get("title", "") or ""
        out.append({"dataset_id": dsid, "title": title})
    return out


# ----------------
# export dataset as parquet
# ----------------
async def get_dataset_bytes(client, dataset_id: str) -> bytes:
    try:
        # Export dataset as parquet bytes
        parquet_bytes = await client.export(dataset_id, "parquet")
    
        return parquet_bytes
        
    except Exception as e:
        print(f"Error exporting dataset: {e}")
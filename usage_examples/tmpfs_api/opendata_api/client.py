# bologna_opendata.py
import httpx
from typing import Optional, Dict, Any

BASE_URL = "https://opendata.comune.bologna.it/api/explore/v2.1"

class BolognaOpenData:
    def __init__(self, timeout: float = 20.0):
        """
        Initialize the async HTTP client.

        Args:
            timeout: request timeout in seconds (default 20.0).
        """
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)

    async def close(self):
        """
        Close the underlying HTTP client.
        Must be called at the end of usage to free sockets.
        """
        await self._client.aclose()

    async def list_datasets(
        self,
        q: Optional[str] = None,
        where: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search the catalog (list datasets).

        This works at the *dataset level* (not rows inside a dataset).

        Args:
            q: (optional) search string. If provided, the client builds a
               safe ODSQL query using search('q').
               Example: q="residenti"
            where: (optional) raw ODSQL filter. Only needed if you want
                   precise catalog filters (e.g., theme='Ambiente').
                   In most cases you don't need this.
            limit: number of datasets to return (default 20).
            offset: pagination offset (default 0).

        Returns:
            A JSON dict with a "results" list. Each item includes
            dataset_id, metas.default.title, description, etc.

        Notes:
            - In Bologna's portal, q is internally translated to
              where=search('term').
            - The 'where' param here is rarely needed at catalog level,
              except for advanced filtering by theme/keyword.
        """
        params = {"limit": limit, "offset": offset}
        if where:
            params["where"] = where
        elif q:
            esc = q.replace("'", "''")
            params["where"] = f"search('{esc}')"

        r = await self._client.get("/catalog/datasets", params=params)
        r.raise_for_status()
        return r.json()

    async def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """
        Get metadata for a specific dataset.

        Args:
            dataset_id: the id string from the catalog (e.g.,
                        "numero-di-residenti-per-quartiere").

        Returns:
            JSON dict containing dataset info, including schema/fields.
        """
        r = await self._client.get(f"/catalog/datasets/{dataset_id}")
        r.raise_for_status()
        return r.json()

    async def query_records(
        self,
        dataset_id: str,
        select: str = "*",
        where: Optional[str] = None,
        order_by: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Query rows from a dataset using ODSQL.

        Args:
            dataset_id: dataset id string.
            select: comma-separated list of columns (default "*").
            where: ODSQL filter, e.g. "quartiere='Navile' AND anno=2023".
            order_by: ODSQL order clause, e.g. "anno DESC".
            limit: number of rows to fetch (default 100).
            offset: pagination offset (default 0).

        Returns:
            JSON dict with a "results" list, each element a row (dict).

        Notes:
            This is the main method for slicing data by condition.
            Without a where/limit, you can easily request thousands
            of rows, so always filter.
        """
        params = {"select": select, "limit": limit, "offset": offset}
        if where:   # we won't use where in agentic workflows, we'll take it out when using this as a @tool
            params["where"] = where
        if order_by:
            params["order_by"] = order_by

        r = await self._client.get(
            f"/catalog/datasets/{dataset_id}/records", params=params
        )
        r.raise_for_status()
        return r.json()

    async def export(
        self,
        dataset_id: str,
        fmt: str = "parquet"
    ) -> bytes:
        """
        Download the full dataset in one file (no row limit).

        Args:
            dataset_id: dataset id string.
            fmt: format string. Typical values: "csv", "json",
                 "geojson", "parquet".
                 Default is "parquet".

        Returns:
            Raw bytes of the file. Caller should save to disk.

        Example:
            blob = await client.export("numero-di-residenti-per-quartiere", "csv")
            with open("residenti.csv", "wb") as f:
                f.write(blob)
        """
        r = await self._client.get(f"/catalog/datasets/{dataset_id}/exports/{fmt}")
        r.raise_for_status()
        return r.content
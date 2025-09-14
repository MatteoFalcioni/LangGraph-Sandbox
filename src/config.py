# src/config.py
from __future__ import annotations

import os
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any


class SessionStorage(str, Enum):
    """Where /session lives."""
    TMPFS = "TMPFS"  # /session is RAM-backed tmpfs (ephemeral, fast)
    BIND  = "BIND"   # /session is a host bind mount ./sessions/<sid> (persistent)


class DatasetAccess(str, Enum):
    """How datasets are made available inside the sandbox."""
    NONE      = "NONE"       # no datasets - simple sandbox mode
    LOCAL_RO  = "LOCAL_RO"   # host datasets mounted read-only at /data
    API = "API"  # datasets fetched on demand into /session/data


@dataclass(frozen=True)
class Config:
    # --- core knobs (defaults are recommended prod/demo) ---
    session_storage: SessionStorage = SessionStorage.TMPFS
    dataset_access:  DatasetAccess  = DatasetAccess.API

    # --- paths (host-side) ---
    sessions_root: Path = Path("./sessions")      # for BIND mode and saving logs/registry
    datasets_host_ro: Optional[Path] = None       # required if DatasetAccess=LOCAL_RO
    blobstore_dir: Path = Path("./blobstore")
    artifacts_db_path: Path = Path("./artifacts.db")

    # --- docker bits / misc ---
    sandbox_image: str = "py-sandbox:latest"
    tmpfs_size_mb: int = 1024  # only used when SessionStorage=TMPFS

    # --- in-container canonical paths (do not change lightly) ---
    container_session_path: str = "/session"
    container_data_staged: str  = "/session/data"  # for API
    container_data_ro: str      = "/data"          # for LOCAL_RO

    # ---------- helpers ----------

    @property
    def is_tmpfs(self) -> bool:
        return self.session_storage == SessionStorage.TMPFS

    @property
    def is_bind(self) -> bool:
        return self.session_storage == SessionStorage.BIND

    @property
    def uses_api_staging(self) -> bool:
        return self.dataset_access == DatasetAccess.API

    @property
    def uses_local_ro(self) -> bool:
        return self.dataset_access == DatasetAccess.LOCAL_RO

    @property
    def uses_no_datasets(self) -> bool:
        return self.dataset_access == DatasetAccess.NONE

    def mode_id(self) -> str:
        """
        Returns the identifier from the README table:
          BIND_NONE: BIND + NONE
          TMPFS_NONE: TMPFS + NONE
          BIND_LOCAL: BIND + LOCAL_RO
          TMPFS_LOCAL: TMPFS + LOCAL_RO
          TMPFS_API: TMPFS + API (default)
          BIND_API: BIND + API
        """
        if self.is_bind and self.uses_no_datasets:
            return "BIND_NONE"  # "A"
        if self.is_tmpfs and self.uses_no_datasets:
            return "TMPFS_NONE"  # "B"
        if self.is_bind and self.uses_local_ro:
            return "BIND_LOCAL"  # "C"
        if self.is_tmpfs and self.uses_local_ro:
            return "TMPFS_LOCAL"  # "D"
        if self.is_tmpfs and self.uses_api_staging:
            return "TMPFS_API"  # "E"
        return "BIND_API"  # "F"

    def session_dir(self, session_id: str) -> Path:
        """Host-side folder for this session (used in BIND mode and for logs/exports)."""
        return self.sessions_root / session_id

    # ---------- construction ----------

    @staticmethod
    def _load_env_file(env_file_path: Optional[Path]) -> Dict[str, str]:
        """Load environment variables from a file if provided."""
        if env_file_path is None:
            return {}
        
        env_vars = {}
        if env_file_path.exists():
            with open(env_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=VALUE format (handle inline comments)
                    if '=' in line:
                        key, value = line.split('=', 1)
                        # Remove inline comments (everything after #)
                        if '#' in value:
                            value = value.split('#')[0]
                        env_vars[key.strip()] = value.strip()
        return env_vars

    @staticmethod
    def _get_env_enum(name: str, enum_cls, default, env_vars: Optional[Dict[str, str]] = None):
        # First check file env vars, then system env vars
        raw = None
        if env_vars and name in env_vars:
            raw = env_vars[name]
        else:
            raw = os.getenv(name, None)
        
        if raw is None or raw.strip() == "":
            return default  # use the enum default directly
        try:
            return enum_cls(raw.strip().upper())
        except Exception:
            allowed = ", ".join(e.value for e in enum_cls)
            raise ValueError(f"{name} must be one of: {allowed} (got: {raw!r})")

    @staticmethod
    def _get_env_value(name: str, default: str = None, env_vars: Optional[Dict[str, str]] = None) -> str:
        """Get environment variable value, checking file first, then system env."""
        if env_vars and name in env_vars:
            return env_vars[name]
        return os.getenv(name, default)

    @classmethod
    def from_env(cls, env_file_path: Optional[Path] = None) -> "Config":
        """
        Load configuration from environment variables, optionally from a file.
        
        Args:
            env_file_path: Optional path to environment file. If provided, variables
                         from the file take precedence over system environment variables.
        
        Environment variables:
          - SESSION_STORAGE = TMPFS | BIND           (default: TMPFS)
          - DATASET_ACCESS  = NONE | LOCAL_RO | API   (default: API)
          - SESSIONS_ROOT   = ./sessions
          - DATASETS_HOST_RO= ./example_llm_data     (required if LOCAL_RO)
          - BLOBSTORE_DIR   = ./blobstore
          - ARTIFACTS_DB    = ./artifacts.db
          - SANDBOX_IMAGE   = py-sandbox:latest
          - TMPFS_SIZE_MB   = 1024
        """
        # Load environment variables from file if provided
        env_vars = cls._load_env_file(env_file_path)
        
        session_storage = cls._get_env_enum("SESSION_STORAGE", SessionStorage, SessionStorage.TMPFS, env_vars)
        dataset_access  = cls._get_env_enum("DATASET_ACCESS",  DatasetAccess,  DatasetAccess.API, env_vars)

        sessions_root   = Path(cls._get_env_value("SESSIONS_ROOT", "./sessions", env_vars)).resolve()
        datasets_host_ro_env = cls._get_env_value("DATASETS_HOST_RO", None, env_vars)
        datasets_host_ro = Path(datasets_host_ro_env).resolve() if datasets_host_ro_env else None

        blobstore_dir   = Path(cls._get_env_value("BLOBSTORE_DIR", "./blobstore", env_vars)).resolve()
        artifacts_db    = Path(cls._get_env_value("ARTIFACTS_DB", "./artifacts.db", env_vars)).resolve()
        sandbox_image   = cls._get_env_value("SANDBOX_IMAGE", "py-sandbox:latest", env_vars)
        tmpfs_size_mb   = int(cls._get_env_value("TMPFS_SIZE_MB", "1024", env_vars))

        # Basic validation
        if dataset_access == DatasetAccess.LOCAL_RO:
            if not datasets_host_ro:
                raise ValueError("DATASETS_HOST_RO is required when DATASET_ACCESS=LOCAL_RO")
            # Don't force existence here; create/mount logic can handle it, but warn early if missing.
        elif dataset_access == DatasetAccess.NONE:
            # NONE mode doesn't need datasets_host_ro
            datasets_host_ro = None
        return cls(
            session_storage=session_storage,
            dataset_access=dataset_access,
            sessions_root=sessions_root,
            datasets_host_ro=datasets_host_ro,
            blobstore_dir=blobstore_dir,
            artifacts_db_path=artifacts_db,
            sandbox_image=sandbox_image,
            tmpfs_size_mb=tmpfs_size_mb,
        )

if __name__ == "__main__":
    # Load once at startup
    from src.config import Config
    CFG = Config.from_env()
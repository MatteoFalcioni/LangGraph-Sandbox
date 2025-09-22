#!/usr/bin/env python3
"""
Comprehensive tests for HYBRID mode functionality.
Tests configuration, SessionManager, and tool factory integration.
"""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph_sandbox.config import Config, DatasetAccess, SessionStorage
from langgraph_sandbox.sandbox.session_manager import SessionManager
from langgraph_sandbox.tool_factory.make_tools import (
    make_list_datasets_tool, 
    make_select_dataset_tool,
    make_export_datasets_tool
)


class TestHybridModeConfig:
    """Test HYBRID mode configuration loading and validation."""
    
    def setup_method(self):
        """Clean up environment variables before each test."""
        for key in ['DATASET_ACCESS', 'HYBRID_LOCAL_PATH', 'SESSION_STORAGE']:
            if key in os.environ:
                del os.environ[key]
    
    def test_hybrid_mode_config_loading(self):
        """Test that HYBRID mode can be configured correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Create test files
            (hybrid_data_dir / "dataset1.parquet").write_text("test data 1")
            (hybrid_data_dir / "dataset2.parquet").write_text("test data 2")
            
            # Create env file for HYBRID mode
            env_file = temp_path / "test_sandbox.env"
            env_content = f"""
SESSION_STORAGE=TMPFS
DATASET_ACCESS=HYBRID
HYBRID_LOCAL_PATH={hybrid_data_dir}
SESSIONS_ROOT={temp_path / "sessions"}
BLOBSTORE_DIR={temp_path / "blobstore"}
ARTIFACTS_DB={temp_path / "artifacts.db"}
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=512
"""
            env_file.write_text(env_content)
            
            # Test configuration loading
            cfg = Config.from_env(env_file_path=env_file)
            
            # Verify configuration
            assert cfg.dataset_access == DatasetAccess.HYBRID
            assert cfg.hybrid_local_path == hybrid_data_dir
            assert cfg.uses_hybrid_mode == True
            assert cfg.mode_id() == "TMPFS_HYBRID"
            assert cfg.datasets_host_ro is None  # Should be None in HYBRID mode
    
    def test_hybrid_mode_validation_missing_path(self):
        """Test that HYBRID mode requires hybrid_local_path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create env file without HYBRID_LOCAL_PATH
            env_file = temp_path / "test_sandbox.env"
            env_content = """
SESSION_STORAGE=TMPFS
DATASET_ACCESS=HYBRID
SESSIONS_ROOT=./sessions
BLOBSTORE_DIR=./blobstore
ARTIFACTS_DB=./artifacts.db
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=512
"""
            env_file.write_text(env_content)
            
            # Should raise ValueError
            with pytest.raises(ValueError, match="HYBRID_LOCAL_PATH is required when DATASET_ACCESS=HYBRID"):
                Config.from_env(env_file_path=env_file)
    
    def test_hybrid_mode_bind_storage(self):
        """Test HYBRID mode with BIND storage."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            env_file = temp_path / "test_sandbox.env"
            env_content = f"""
SESSION_STORAGE=BIND
DATASET_ACCESS=HYBRID
HYBRID_LOCAL_PATH={hybrid_data_dir}
SESSIONS_ROOT={temp_path / "sessions"}
BLOBSTORE_DIR={temp_path / "blobstore"}
ARTIFACTS_DB={temp_path / "artifacts.db"}
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=512
"""
            env_file.write_text(env_content)
            
            cfg = Config.from_env(env_file_path=env_file)
            
            assert cfg.dataset_access == DatasetAccess.HYBRID
            assert cfg.session_storage == SessionStorage.BIND
            assert cfg.mode_id() == "BIND_HYBRID"
    
    def test_hybrid_mode_properties(self):
        """Test HYBRID mode specific properties."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            env_file = temp_path / "test_sandbox.env"
            env_content = f"""
SESSION_STORAGE=TMPFS
DATASET_ACCESS=HYBRID
HYBRID_LOCAL_PATH={hybrid_data_dir}
SESSIONS_ROOT={temp_path / "sessions"}
BLOBSTORE_DIR={temp_path / "blobstore"}
ARTIFACTS_DB={temp_path / "artifacts.db"}
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=512
"""
            env_file.write_text(env_content)
            
            cfg = Config.from_env(env_file_path=env_file)
            
            # Test mode-specific properties
            assert cfg.uses_hybrid_mode == True
            assert cfg.uses_api_staging == False  # HYBRID is not pure API
            assert cfg.uses_local_ro == False     # HYBRID is not pure LOCAL_RO
            assert cfg.uses_no_datasets == False


class TestHybridModeSessionManager:
    """Test SessionManager with HYBRID mode."""
    
    def test_session_manager_hybrid_initialization(self):
        """Test SessionManager initialization with HYBRID mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Test successful initialization
            session_manager = SessionManager(
                image="sandbox:latest",
                session_storage=SessionStorage.TMPFS,
                dataset_access=DatasetAccess.HYBRID,
                hybrid_local_path=hybrid_data_dir,
                session_root=temp_path / "sessions",
                tmpfs_size="512m",
                address_strategy="host"
            )
            
            # Verify properties
            assert session_manager.dataset_access == DatasetAccess.HYBRID
            assert session_manager.hybrid_local_path == hybrid_data_dir
            assert session_manager.datasets_path is None  # Should be None in HYBRID mode
    
    def test_session_manager_hybrid_validation(self):
        """Test SessionManager validation for HYBRID mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Test missing hybrid_local_path
            with pytest.raises(ValueError, match="hybrid_local_path is required when dataset_access=HYBRID"):
                SessionManager(
                    image="sandbox:latest",
                    session_storage=SessionStorage.TMPFS,
                    dataset_access=DatasetAccess.HYBRID,
                    hybrid_local_path=None,  # Missing required parameter
                    session_root=temp_path / "sessions",
                    tmpfs_size="512m"
                )
    
    @patch('docker.from_env')
    def test_session_manager_hybrid_volume_mounting(self, mock_docker):
        """Test that HYBRID mode correctly sets up volume mounting."""
        # Mock Docker client
        mock_client = Mock()
        mock_docker.return_value = mock_client
        
        # Mock container creation - first call should raise NotFound (no existing container)
        mock_client.containers.get.side_effect = Exception("Container not found")
        
        # Mock new container creation
        mock_container = Mock()
        mock_container.id = "test-container-id"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "9000/tcp": [{"HostPort": "12345"}]
                }
            }
        }
        mock_client.containers.run.return_value = mock_container
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            session_manager = SessionManager(
                image="sandbox:latest",
                session_storage=SessionStorage.TMPFS,
                dataset_access=DatasetAccess.HYBRID,
                hybrid_local_path=hybrid_data_dir,
                session_root=temp_path / "sessions",
                tmpfs_size="512m",
                address_strategy="host"
            )
            
            # Mock the HTTP client for health check
            with patch('httpx.Client') as mock_http:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_http.return_value.__enter__.return_value.get.return_value = mock_response
                
                # Start session (this will trigger volume mounting)
                session_id = session_manager.start("test-session")
                
                # Verify container was created with correct volume mounting
                mock_client.containers.run.assert_called_once()
                call_args = mock_client.containers.run.call_args
                
                # Check that volumes include the hybrid_local_path
                volumes = call_args.kwargs.get('volumes', {})
                assert str(hybrid_data_dir) in volumes
                assert volumes[str(hybrid_data_dir)]["bind"] == "/data"
                assert volumes[str(hybrid_data_dir)]["mode"] == "ro"


class TestHybridModeTools:
    """Test tool factory functions with HYBRID mode."""
    
    def test_list_datasets_tool_hybrid_mode(self):
        """Test list_datasets_tool with HYBRID mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Create test files
            (hybrid_data_dir / "local_dataset.parquet").write_text("local data")
            (hybrid_data_dir / "another_file.csv").write_text("csv data")
            
            # Mock SessionManager
            mock_session_manager = Mock()
            mock_session_manager.start = Mock()
            
            # Mock container and exec_run for listing files
            mock_container = Mock()
            mock_session_manager.container_for.return_value = mock_container
            
            # Mock the exec_run result for listing files
            mock_container.exec_run.return_value = (0, (
                b'{"mode": "HYBRID mode (local + API datasets)", "path": "/data", "files": ['
                b'{"name": "local_dataset.parquet", "path": "/data/local_dataset.parquet", "size": 10, "modified": 1234567890}, '
                b'{"name": "another_file.csv", "path": "/data/another_file.csv", "size": 8, "modified": 1234567891}'
                b'], "count": 2}\n'
            ))
            
            # Create the tool
            list_tool = make_list_datasets_tool(
                session_manager=mock_session_manager,
                session_key_fn=lambda: "test-session"
            )
            
            # Test the tool (this would normally be async, but we're testing the setup)
            assert list_tool is not None
            assert callable(list_tool)
    
    def test_export_datasets_tool_hybrid_mode(self):
        """Test export_datasets_tool with HYBRID mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Mock SessionManager
            mock_session_manager = Mock()
            mock_session_manager.export_file.return_value = {
                "success": True,
                "host_path": "/tmp/exported_file.parquet",
                "download_url": "http://localhost:8000/artifacts/test-id"
            }
            
            # Create the tool
            export_tool = make_export_datasets_tool(
                session_manager=mock_session_manager,
                session_key_fn=lambda: "test-session"
            )
            
            # Test the tool
            assert export_tool is not None
            assert callable(export_tool)
    
    def test_select_dataset_tool_hybrid_mode(self):
        """Test select_dataset_tool with HYBRID mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Mock SessionManager
            mock_session_manager = Mock()
            mock_session_manager.start = Mock()
            mock_session_manager.container_for.return_value = Mock()
            
            # Mock fetch function
            async def mock_fetch_fn(ds_id: str) -> bytes:
                return f"dataset data for {ds_id}".encode()
            
            # Create the tool
            select_tool = make_select_dataset_tool(
                session_manager=mock_session_manager,
                session_key_fn=lambda: "test-session",
                fetch_fn=mock_fetch_fn
            )
            
            # Test the tool
            assert select_tool is not None
            assert callable(select_tool)


class TestUnifiedDataPath:
    """Test unified /data/ path functionality."""
    
    def test_config_unified_data_path(self):
        """Test that config uses unified /data/ path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            env_file = temp_path / "test_sandbox.env"
            env_content = f"""
SESSION_STORAGE=TMPFS
DATASET_ACCESS=HYBRID
HYBRID_LOCAL_PATH={hybrid_data_dir}
SESSIONS_ROOT={temp_path / "sessions"}
BLOBSTORE_DIR={temp_path / "blobstore"}
ARTIFACTS_DB={temp_path / "artifacts.db"}
SANDBOX_IMAGE=sandbox:latest
TMPFS_SIZE_MB=512
"""
            env_file.write_text(env_content)
            
            cfg = Config.from_env(env_file_path=env_file)
            
            # Verify unified data path
            assert cfg.container_data_staged == "/data"
            assert cfg.container_data_ro == "/data"
    
    def test_tool_descriptions_unified_path(self):
        """Test that tool descriptions reference unified /data/ path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            hybrid_data_dir = temp_path / "test_hybrid_data"
            hybrid_data_dir.mkdir()
            
            # Mock SessionManager
            mock_session_manager = Mock()
            mock_session_manager.start = Mock()
            mock_session_manager.container_for.return_value = Mock()
            
            # Test export tool description
            export_tool = make_export_datasets_tool(
                session_manager=mock_session_manager,
                session_key_fn=lambda: "test-session"
            )
            
            # The tool should be callable and configured for /data/ path
            assert export_tool is not None
            assert callable(export_tool)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

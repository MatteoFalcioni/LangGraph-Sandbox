"""
Utility functions for Docker container management in the sandbox system.
"""

import docker
from typing import List, Optional


def cleanup_sandbox_containers(container_prefix: str = "sbox-", verbose: bool = True) -> List[str]:
    """
    Clean up existing sandbox containers to avoid conflicts.
    
    Args:
        container_prefix: Prefix to match container names (default: "sbox-")
        verbose: Whether to print cleanup messages
        
    Returns:
        List of container names that were removed
        
    Raises:
        Exception: If Docker client cannot be initialized
    """
    removed_containers = []
    
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": container_prefix})
        
        if verbose and containers:
            print(f"Cleaning up {len(containers)} existing sandbox containers...")
        
        for container in containers:
            try:
                container.stop()
                container.remove()
                removed_containers.append(container.name)
                if verbose:
                    print(f"  Removed container: {container.name}")
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not remove {container.name}: {e}")
                    
    except Exception as e:
        if verbose:
            print(f"Warning: Could not clean up containers: {e}")
        raise
    
    return removed_containers


def cleanup_specific_containers(container_names: List[str], verbose: bool = True) -> List[str]:
    """
    Clean up specific containers by name.
    
    Args:
        container_names: List of container names to remove
        verbose: Whether to print cleanup messages
        
    Returns:
        List of container names that were successfully removed
    """
    removed_containers = []
    
    try:
        client = docker.from_env()
        
        for container_name in container_names:
            try:
                container = client.containers.get(container_name)
                container.stop()
                container.remove()
                removed_containers.append(container_name)
                if verbose:
                    print(f"  Removed container: {container_name}")
            except docker.errors.NotFound:
                if verbose:
                    print(f"  Container not found: {container_name}")
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not remove {container_name}: {e}")
                    
    except Exception as e:
        if verbose:
            print(f"Warning: Could not clean up containers: {e}")
        raise
    
    return removed_containers


def list_sandbox_containers(container_prefix: str = "sbox-", running_only: bool = False) -> List[str]:
    """
    List existing sandbox containers.
    
    Args:
        container_prefix: Prefix to match container names (default: "sbox-")
        running_only: If True, only return running containers
        
    Returns:
        List of container names
    """
    try:
        client = docker.from_env()
        containers = client.containers.list(all=not running_only, filters={"name": container_prefix})
        return [container.name for container in containers]
    except Exception as e:
        print(f"Warning: Could not list containers: {e}")
        return []

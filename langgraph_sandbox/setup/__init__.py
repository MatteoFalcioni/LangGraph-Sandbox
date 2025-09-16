#!/usr/bin/env python3
"""
Docker setup script for langgraph-sandbox package.
Run this after installing the package to build the Docker image.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import pkg_resources


def get_package_path():
    """Get the path where the package is installed."""
    try:
        # Get the package location
        package_path = pkg_resources.get_distribution('langgraph-sandbox').location
        return Path(package_path)
    except pkg_resources.DistributionNotFound:
        print("Error: langgraph-sandbox package not found. Please install it first.")
        sys.exit(1)


def copy_docker_files(package_path, target_dir):
    """Copy Docker-related files from package to target directory."""
    target_path = Path(target_dir)
    target_path.mkdir(exist_ok=True)
    
    # Get the setup package directory (where this script is located)
    setup_dir = Path(__file__).parent
    
    # Copy Dockerfile
    dockerfile_src = setup_dir / "Dockerfile"
    if dockerfile_src.exists():
        shutil.copy2(dockerfile_src, target_path / "Dockerfile")
        print(f"✓ Copied Dockerfile to {target_path}")
    else:
        print("Warning: Dockerfile not found in package")
    
    # Copy example.env
    example_env_src = setup_dir / "example.env"
    if example_env_src.exists():
        shutil.copy2(example_env_src, target_path / "example.env")
        print(f"✓ Copied example.env to {target_path}")
    else:
        print("Warning: example.env not found in package")
    
    # Copy docker.env
    docker_env_src = setup_dir / "docker.env"
    if docker_env_src.exists():
        shutil.copy2(docker_env_src, target_path / "docker.env")
        print(f"✓ Copied docker.env to {target_path}")
    else:
        print("Warning: docker.env not found in package")
    
    # Copy required source files for Docker build
    copy_source_files(package_path, target_path)


def copy_source_files(package_path, target_path):
    """Copy required source files for Docker build."""
    # Create src directory structure
    src_dir = target_path / "src"
    src_dir.mkdir(exist_ok=True)
    
    sandbox_dir = src_dir / "sandbox"
    sandbox_dir.mkdir(exist_ok=True)
    
    # Copy repl_server.py from the installed package
    try:
        import sandbox.repl_server
        repl_server_path = Path(sandbox.repl_server.__file__)
        shutil.copy2(repl_server_path, sandbox_dir / "repl_server.py")
        print(f"✓ Copied repl_server.py to {sandbox_dir}")
    except ImportError:
        print("Warning: Could not find repl_server.py in package")
    
    # Copy other required files if they exist
    try:
        import config
        config_path = Path(config.__file__)
        shutil.copy2(config_path, src_dir / "config.py")
        print(f"✓ Copied config.py to {src_dir}")
    except ImportError:
        print("Warning: Could not find config.py in package")


def build_docker_image(image_name="sandbox", tag="latest"):
    """Build the Docker image."""
    print(f"\nBuilding Docker image: {image_name}:{tag}")
    
    try:
        # Build the Docker image
        cmd = ["docker", "build", "-t", f"{image_name}:{tag}", "."]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✓ Docker image built successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Docker build failed: {e}")
        print(f"Error output: {e.stderr}")
        return False
    except FileNotFoundError:
        print("✗ Docker not found. Please install Docker first.")
        return False


def create_env_file(target_dir):
    """Create a .env file from example.env if it doesn't exist."""
    target_path = Path(target_dir)
    env_file = target_path / ".env"
    example_env = target_path / "example.env"
    
    if not env_file.exists() and example_env.exists():
        shutil.copy2(example_env, env_file)
        print(f"✓ Created .env file from example.env")
        print(f"  Edit {env_file} to customize your configuration")
    elif env_file.exists():
        print(f"✓ .env file already exists at {env_file}")
    else:
        print("Warning: No example.env found to create .env from")


def main():
    """Main setup function."""
    print("🐳 LangGraph-Sandbox Docker Setup")
    print("=" * 40)
    
    # Get current working directory
    current_dir = Path.cwd()
    print(f"Working directory: {current_dir}")
    
    # Get package path
    package_path = get_package_path()
    print(f"Package location: {package_path}")
    
    # Copy Docker files
    print("\n📁 Copying Docker files...")
    copy_docker_files(package_path, current_dir)
    
    # Create .env file
    print("\n⚙️  Setting up environment...")
    create_env_file(current_dir)
    
    # Build Docker image
    print("\n🔨 Building Docker image...")
    success = build_docker_image()
    
    if success:
        print("\n🎉 Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env file to customize your configuration")
        print("2. Start using the tools in your Python code:")
        print("   from tool_factory import make_code_sandbox_tool")
        print("   from sandbox import SessionManager")
        print("   from config import Config")
        print("\nExample:")
        print("   config = Config.from_env()")
        print("   session_manager = SessionManager(config=config)")
        print("   tool = make_code_sandbox_tool(session_manager=session_manager)")
    else:
        print("\n❌ Setup failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

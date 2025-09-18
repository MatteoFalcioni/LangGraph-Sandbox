#!/usr/bin/env python3
"""
Setup script for LangGraph-Sandbox package
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = []
with open('requirements.txt', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
            requirements.append(line)

setup(
    name="langgraph-sandbox",
    version="0.1.0",
    author="Matteo Falcioni",
    description="A sandbox environment for LangGraph with artifact storage and dataset management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio",
            "black",
            "flake8",
            "mypy",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    entry_points={
        "console_scripts": [
            "langgraph-sandbox=langgraph_sandbox.main:main",
            "sandbox-setup=langgraph_sandbox.setup:setup_sandbox",
        ],
    },
    include_package_data=True,
    package_data={
        "langgraph_sandbox.setup": ["*.env", "Dockerfile"],
    },
)

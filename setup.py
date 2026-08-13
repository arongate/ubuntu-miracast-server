#!/usr/bin/env python3
"""Setup script for Ubuntu Miracast Server."""

from setuptools import setup, find_packages
from pathlib import Path

# Get the long description from the README file
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    with open(readme_path, encoding="utf-8") as f:
        long_description = f.read()

# Get version from VERSION file
with open(Path(__file__).parent / "VERSION") as f:
    version = f.read().strip()

setup(
    name="ubuntu-miracast-server",
    version=version,
    description="Miracast server (sink) for Ubuntu",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ubuntu Miracast Team",
    author_email="example@example.com",
    url="https://github.com/yourusername/ubuntu-miracast-server",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: X11 Applications :: GTK",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Video",
        "Topic :: System :: Networking",
    ],
    python_requires=">=3.10",
    install_requires=[
        # NOTE: PyGObject and pycairo require system libraries.
        # On Ubuntu: sudo apt install python3-gi python3-cairo python3-gst-1.0
        # They are listed here for metadata but may fail to install via pip
        # in environments without the required C libraries and compiler.
        "PyGObject>=3.42.0",
        "pycairo>=1.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "hypothesis>=6.0.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ubuntu-miracast-server=miracast_server.app:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)

# Contributing to Ubuntu Miracast Server

Thank you for your interest in contributing! This document covers the development setup, coding standards, and contribution process.

## Development Setup

### Prerequisites

- Python 3.10+ (3.12 recommended)
- System dependencies (see [Getting Started](docs/getting-started.md#2-install-system-dependencies))
- Git

### Clone and Set Up

```bash
git clone https://github.com/yourusername/ubuntu-miracast-server.git
cd ubuntu-miracast-server

# Create virtual environment with system site-packages
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

# Install with development dependencies
pip install -e ".[dev]"
```

### Verify Your Setup

```bash
# Run tests
make test

# Run linting
make lint

# Format code
make format
```

## Coding Standards

### Style

- **Formatter:** Black (line-length=100)
- **Import sorting:** isort (Black-compatible profile)
- **Linting:** flake8
- **Type checking:** mypy (optional but encouraged)

```bash
# Format everything
black --line-length=100 src/ tests/
isort src/ tests/

# Check without modifying
black --check --line-length=100 src/ tests/
flake8 src/ tests/
```

### Conventions

- Module-level docstrings explain the module's purpose
- Classes and public methods have docstrings (Google style)
- Private methods have brief docstrings or inline comments
- Type hints on all function signatures
- `logger = logging.getLogger(__name__)` at module level
- GObject signal emissions always via `GLib.idle_add()` from non-main threads
- Subprocess calls use list format (never `shell=True`)
- wpa_cli parameters validated through `utils._validate_wpa_param()` before use

### Architecture Rules

1. **UI code never calls subprocess directly** — it goes through core modules
2. **Core modules never import UI** — signals flow upward via GObject
3. **RTSP protocol code is stateless** — `rtsp.py` does pure parsing/building
4. **All file I/O uses atomic writes** — write to `.tmp`, then rename
5. **Config and history files use 0600 permissions**

## Testing

### Running Tests

```bash
# Full test suite
make test

# With verbose output
pytest tests/ -v

# With coverage
make coverage

# Single test file
pytest tests/test_rtsp.py -v

# Single test
pytest tests/test_models.py::TestIncomingConnection::test_valid_connection -v
```

### Writing Tests

- Test files go in `tests/` with the naming pattern `test_<module>.py`
- Use pytest fixtures and `tmp_path` for file operations
- Mock external dependencies (subprocess, sockets, GStreamer)
- Test both valid and invalid inputs
- Use `unittest.mock.patch` for subprocess and system calls

Example test structure:

```python
"""Tests for MiracastAdvertiser."""

from unittest.mock import patch, MagicMock
import pytest
from miracast_server.advertiser import MiracastAdvertiser, _encode_wfd_device_info_subelement


class TestWFDSubelementEncoding:
    """Test WFD sub-element generation."""

    def test_default_port_encoding(self):
        result = _encode_wfd_device_info_subelement(7236)
        assert "1C44" in result  # 7236 = 0x1C44

    def test_custom_port_encoding(self):
        result = _encode_wfd_device_info_subelement(8000)
        assert "1F40" in result  # 8000 = 0x1F40


class TestMiracastAdvertiser:
    """Test advertiser lifecycle."""

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser._find_p2p_interface")
    def test_start_advertising(self, mock_find, mock_wpa):
        mock_find.return_value = ("p2p-dev-wlan0", "wlan0")
        mock_wpa.return_value = "OK"
        
        adv = MiracastAdvertiser()
        adv.start_advertising()
        
        assert adv.is_advertising
```

### What to Test

- ✅ Data validation (models, config rules)
- ✅ Protocol parsing (RTSP messages, WFD parameters)
- ✅ State transitions (advertiser start/stop, connection lifecycle)
- ✅ Error handling (malformed input, timeouts, failures)
- ✅ Security boundaries (parameter validation, size limits)
- ⚠️ GStreamer pipeline (mock element creation, verify structure)
- ❌ Actual Wi-Fi Direct connections (manual testing only)
- ❌ GTK rendering (manual testing only)

## Pull Request Process

### Before Submitting

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with clear, atomic commits

3. **Run the full check suite:**
   ```bash
   make lint
   make test
   ```

4. **Ensure all tests pass** and no new linting errors

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add WPS PIN authentication support
fix: handle RTSP timeout during renegotiation
docs: add troubleshooting section for 5GHz channels
refactor: extract pipeline builder to separate class
test: add property tests for RTSP CSeq handling
chore: update GStreamer dependency to 1.22
```

### PR Description

Include:
- **Summary** of what changed and why
- **Testing** — what was tested, how to verify
- **Breaking changes** if any

### Review Criteria

PRs are reviewed for:
- Correctness and completeness
- Test coverage for new/changed code
- Adherence to coding standards
- Security implications (especially for subprocess/network code)
- Documentation updates where needed

## Reporting Issues

### Bug Reports

Include:
- Ubuntu version, Python version, Wi-Fi adapter model
- Steps to reproduce
- Expected vs. actual behavior
- Log output (`~/.local/share/ubuntu-miracast-server/logs/miracast-server.log`)

### Feature Requests

Describe:
- The use case or problem you're solving
- Proposed solution (if you have one)
- Alternatives you've considered

## Project Governance

This project follows a maintainer model. The maintainers have final say on:
- Architecture decisions
- Dependency additions
- Release timing

All contributions are welcome regardless of size — from typo fixes to major features.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

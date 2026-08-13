# Coding Conventions

## Python Style

- **Formatter:** Black, line-length=100
- **Imports:** isort with Black-compatible profile
- **Linting:** flake8
- **Type hints:** Required on all function signatures. Use `str | None` union syntax (3.10+)
- **Docstrings:** Google-style, required on all public classes and methods

## Naming

- Modules: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`
- GObject signal names: `kebab-case` (e.g., `"stream-started"`)

## Module Structure

```python
"""Module docstring explaining purpose."""

import stdlib_modules
import third_party_modules

import gi
gi.require_version(...)
from gi.repository import ...

from miracast_server.other_module import ...

logger = logging.getLogger(__name__)

# Module-level constants
_PRIVATE_CONSTANT = "value"
PUBLIC_CONSTANT = "value"


class MyClass(GObject.Object):
    """Class docstring."""

    __gsignals__ = { ... }

    def __init__(self, ...):
        """Init docstring."""
        super().__init__()
        ...

    # Public methods first
    def public_method(self) -> ReturnType:
        """Method docstring."""
        ...

    # Private methods after
    def _private_helper(self) -> None:
        ...
```

## Threading Rules

1. **Never emit GObject signals from non-main threads.** Always use:
   ```python
   GLib.idle_add(self.emit, "signal-name", arg)
   ```

2. **Protect shared state with `threading.Lock`** when accessed from multiple threads.

3. **Set `_running = False` before joining threads.** Use 5-second join timeouts.

4. **Daemon threads** for background work (set `daemon=True`).

## Security Rules

1. **No `shell=True`** in subprocess calls. Always use list format.
2. **Validate wpa_cli parameters** through `utils._validate_wpa_param()` before passing to subprocess.
3. **Validate codecs** against the whitelist before pipeline construction.
4. **Size-limit RTSP input** (8KB headers, 64KB body) before parsing.
5. **Use 0600 permissions** for config and history files.
6. **Atomic writes** — write to `.tmp` file, then `rename()`.

## Error Handling

- Log errors with `logger.error()` including context
- Emit error signals for recoverable errors (don't crash)
- Use specific exception types (`ValueError`, `RuntimeError`, `OSError`)
- Never silently swallow exceptions — at minimum log them
- On file I/O failure: retain in-memory state, log error, continue

## GStreamer Conventions

- Pipeline and element names should be descriptive: `"videosink"`, `"udpsrc"`, `"demux"`
- Use `Gst.ElementFactory.make(name, unique_name)` — always provide a unique name
- Check return value of `make()` — it returns None if the element isn't available
- Handle bus messages on the main thread via `bus.add_watch()`

## Test Conventions

- File: `tests/test_<module>.py`
- Class: `TestClassName` grouped by feature
- Method: `test_<behavior_being_tested>`
- Use `pytest` fixtures, not setUp/tearDown
- Use `tmp_path` for file operations
- Mock external dependencies at the boundary (subprocess, socket, GStreamer)
- Assert specific exceptions with `pytest.raises(ExceptionType, match="pattern")`

## Git Conventions

- Branch: `feature/<name>`, `fix/<name>`, `docs/<name>`
- Commits: [Conventional Commits](https://www.conventionalcommits.org/) format
- One logical change per commit
- PR title < 70 characters

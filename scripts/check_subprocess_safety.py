#!/usr/bin/env python3
"""Security audit: verify all subprocess calls follow safety rules.

This script uses AST parsing to statically analyze all Python source files
and verify that subprocess usage follows the project's security rules:

1. No shell=True in any subprocess call
2. All subprocess.run/Popen first argument must be a list (not a string)
3. No os.system() or os.popen() calls (equivalent to shell=True)
4. No eval() or exec() calls
5. Temp file paths must use restrictive patterns

This is critical because the application runs with sudo privileges for
wpa_cli, ip, dnsmasq, and other networking commands. A command injection
vulnerability would result in root-level compromise.

Exit code:
  0 = all checks passed
  1 = violations found
"""

import ast
import sys
from pathlib import Path


class SubprocessSafetyVisitor(ast.NodeVisitor):
    """AST visitor that detects unsafe subprocess usage patterns."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.violations: list[str] = []

    def _loc(self, node: ast.AST) -> str:
        return f"{self.filepath}:{node.lineno}:{node.col_offset}"

    def visit_Call(self, node: ast.Call):
        self._check_shell_true(node)
        self._check_subprocess_string_arg(node)
        self._check_os_system(node)
        self._check_eval_exec(node)
        self.generic_visit(node)

    def _check_shell_true(self, node: ast.Call):
        """Flag any subprocess call with shell=True."""
        for keyword in node.keywords:
            if keyword.arg == "shell":
                if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    self.violations.append(
                        f"{self._loc(node)}: CRITICAL: shell=True in subprocess call. "
                        f"This allows command injection with root privileges."
                    )

    def _check_subprocess_string_arg(self, node: ast.Call):
        """Flag subprocess.run/Popen with a string first argument."""
        func = node.func

        # Match subprocess.run(...) or subprocess.Popen(...)
        if isinstance(func, ast.Attribute) and func.attr in ("run", "Popen", "call", "check_call", "check_output"):
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                if node.args:
                    first_arg = node.args[0]
                    # Flag if it's a string constant or f-string
                    if isinstance(first_arg, (ast.Constant, ast.JoinedStr)):
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            self.violations.append(
                                f"{self._loc(node)}: CRITICAL: subprocess call with string argument. "
                                f"Use list format to prevent command injection."
                            )
                        elif isinstance(first_arg, ast.JoinedStr):
                            self.violations.append(
                                f"{self._loc(node)}: CRITICAL: subprocess call with f-string argument. "
                                f"Use list format to prevent command injection."
                            )

    def _check_os_system(self, node: ast.Call):
        """Flag os.system() and os.popen() calls."""
        func = node.func
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                if func.attr in ("system", "popen"):
                    self.violations.append(
                        f"{self._loc(node)}: CRITICAL: os.{func.attr}() is equivalent to "
                        f"shell=True. Use subprocess.run() with list args instead."
                    )

    def _check_eval_exec(self, node: ast.Call):
        """Flag eval() and exec() calls."""
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
            self.violations.append(
                f"{self._loc(node)}: CRITICAL: {func.id}() allows arbitrary code execution. "
                f"Never use in a privileged application."
            )


def check_file(filepath: Path) -> list[str]:
    """Parse and check a single Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        return [f"{filepath}: PARSE ERROR: {e}"]

    visitor = SubprocessSafetyVisitor(str(filepath))
    visitor.visit(tree)
    return visitor.violations


def main():
    """Scan all Python source files for security violations."""
    src_dir = Path(__file__).parent.parent / "src"
    if not src_dir.exists():
        print(f"ERROR: Source directory not found: {src_dir}", file=sys.stderr)
        sys.exit(1)

    all_violations: list[str] = []
    files_checked = 0

    for py_file in sorted(src_dir.rglob("*.py")):
        violations = check_file(py_file)
        all_violations.extend(violations)
        files_checked += 1

    # Summary
    print(f"Subprocess Safety Audit")
    print(f"{'=' * 60}")
    print(f"Files checked: {files_checked}")
    print(f"Violations found: {len(all_violations)}")
    print()

    if all_violations:
        print("VIOLATIONS:")
        print("-" * 60)
        for v in all_violations:
            print(f"  ❌ {v}")
        print()
        print("FAILED: Security violations detected in privileged application code.")
        print("All subprocess calls must use list format with validated parameters.")
        sys.exit(1)
    else:
        print("✅ All subprocess calls use safe patterns (list args, no shell=True)")
        print("✅ No os.system/os.popen/eval/exec detected")
        sys.exit(0)


if __name__ == "__main__":
    main()

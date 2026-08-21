"""The fixed, safe tool set given to the AI model.

Every tool is backed by a read-only Rust function exposed through the
``cosmya._native`` PyO3 extension. There is intentionally NO generic
``run_command`` / shell-execution tool: the AI can only call these six
predefined, schema-validated, sandboxed operations.

If the native extension has not been built (e.g. in a development checkout
before running ``build.sh`` / ``maturin develop``), calling any tool raises
:class:`NativeExtensionMissingError` with a clear, actionable message rather
than failing with an opaque ``ImportError`` deep in the agent loop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cosmya.ai.models import ToolDefinition

try:
    from cosmya import _native  # type: ignore[attr-defined]

    _NATIVE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without a Rust build
    _native = None  # type: ignore[assignment]
    _NATIVE_AVAILABLE = False


class NativeExtensionMissingError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Cosmya's native Rust inspection engine (cosmya._native) is not "
            "built. Run `maturin develop` in `rust/` during development, or "
            "install Cosmya via the official .deb package, which bundles the "
            "compiled extension."
        )


TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name="list_directory",
        description=(
            "List the immediate contents (files and subdirectories) of a "
            "directory inside the project. Path is relative to the project root."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the project root ('.' for root).",
                }
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="tree",
        description=(
            "Return a recursive directory tree starting at the given path, "
            "up to a bounded depth. Useful for getting an overview of project structure."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the project root.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth (default 5, max 12).",
                    "minimum": 1,
                    "maximum": 12,
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="read_file",
        description=(
            "Read the text content of a single file inside the project. "
            "Binary files are rejected and oversized files are truncated with a notice."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the project root.",
                }
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="search_text",
        description=(
            "Search for a regular-expression pattern across text files under a path, "
            "returning matching lines with file/line locations. Results are bounded."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the project root to search within.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 100, max 500).",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
            "required": ["pattern", "path"],
        },
    ),
    ToolDefinition(
        name="search_files",
        description=(
            "Find files under a path whose name matches a glob pattern "
            "(e.g. '*.py', '**/test_*.py'). Results are bounded."
        ),
        parameters={
            "type": "object",
            "properties": {
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to match file names against.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the project root.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 200, max 1000).",
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            "required": ["glob", "path"],
        },
    ),
    ToolDefinition(
        name="file_info",
        description=(
            "Return metadata about a single file or directory: size, type, "
            "whether it appears to be binary, and last-modified time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the project root.",
                }
            },
            "required": ["path"],
        },
    ),
]

_TOOL_NAMES = {t.name for t in TOOL_DEFINITIONS}


class ToolExecutor:
    """Dispatches validated tool calls to the native Rust sandboxed engine."""

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self._dispatch: dict[str, Callable[..., dict[str, Any]]] = {
            "list_directory": self._call("list_directory"),
            "tree": self._call("tree"),
            "read_file": self._call("read_file"),
            "search_text": self._call("search_text"),
            "search_files": self._call("search_files"),
            "file_info": self._call("file_info"),
        }

    def _call(self, native_fn_name: str) -> Callable[..., dict[str, Any]]:
        def _invoke(**kwargs: Any) -> dict[str, Any]:
            if not _NATIVE_AVAILABLE:
                raise NativeExtensionMissingError()
            native_fn = getattr(_native, native_fn_name)
            return native_fn(self.project_root, **kwargs)

        return _invoke

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call and return a structured result.

        Unknown tool names and native-layer exceptions are converted into a
        structured ``{"success": False, "error": ...}`` result rather than
        propagating raw exceptions back into the agent loop -- the AI is
        untrusted, so it must always receive a well-formed, bounded response.
        """
        if tool_name not in _TOOL_NAMES:
            return {"success": False, "error": f"Unknown tool: {tool_name!r}"}
        try:
            result = self._dispatch[tool_name](**arguments)
        except NativeExtensionMissingError:
            raise
        except Exception as exc:  # native layer raised something unexpected
            return {"success": False, "error": f"Tool '{tool_name}' failed: {exc}"}
        return result

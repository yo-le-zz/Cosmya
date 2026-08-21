import sys
import types

import pytest


@pytest.fixture
def fake_native(monkeypatch):
    """Install a fake cosmya._native module so ToolExecutor can be tested
    without the compiled Rust extension."""
    fake_module = types.ModuleType("cosmya._native")

    def list_directory(root, path):
        return {"success": True, "path": path, "entries": ["a.py", "b.py"]}

    def tree(root, path, max_depth=5):
        return {"success": True, "path": path, "tree": "a.py\nb.py"}

    def read_file(root, path):
        if path == "../../etc/passwd" or path.startswith("/"):
            return {"success": False, "error": "Path escapes project root."}
        return {
            "success": True,
            "path": path,
            "content": "print('hi')",
            "truncated": False,
        }

    def search_text(root, pattern, path, max_results=100):
        return {"success": True, "matches": []}

    def search_files(root, glob, path, max_results=200):
        return {"success": True, "matches": ["a.py"]}

    def file_info(root, path):
        return {"success": True, "path": path, "size": 42, "is_binary": False}

    fake_module.list_directory = list_directory
    fake_module.tree = tree
    fake_module.read_file = read_file
    fake_module.search_text = search_text
    fake_module.search_files = search_files
    fake_module.file_info = file_info

    monkeypatch.setitem(sys.modules, "cosmya._native", fake_module)

    import cosmya.agent.tools as tools_module

    monkeypatch.setattr(tools_module, "_native", fake_module)
    monkeypatch.setattr(tools_module, "_NATIVE_AVAILABLE", True)
    yield fake_module


def test_execute_known_tool_returns_structured_result(fake_native):
    from cosmya.agent.tools import ToolExecutor

    executor = ToolExecutor(project_root="/tmp/project")
    result = executor.execute("read_file", {"path": "a.py"})
    assert result["success"] is True
    assert result["content"] == "print('hi')"


def test_execute_unknown_tool_returns_error_not_exception(fake_native):
    from cosmya.agent.tools import ToolExecutor

    executor = ToolExecutor(project_root="/tmp/project")
    result = executor.execute("run_shell_command", {"cmd": "rm -rf /"})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_no_generic_shell_tool_exists():
    from cosmya.agent.tools import TOOL_DEFINITIONS

    names = {t.name for t in TOOL_DEFINITIONS}
    assert names == {
        "list_directory",
        "tree",
        "read_file",
        "search_text",
        "search_files",
        "file_info",
    }
    for forbidden in ("run_command", "exec", "shell", "bash", "eval"):
        assert forbidden not in names


def test_missing_native_extension_raises_clear_error(monkeypatch):
    import cosmya.agent.tools as tools_module
    from cosmya.agent.tools import NativeExtensionMissingError, ToolExecutor

    monkeypatch.setattr(tools_module, "_NATIVE_AVAILABLE", False)
    executor = ToolExecutor(project_root="/tmp/project")
    with pytest.raises(NativeExtensionMissingError):
        executor.execute("read_file", {"path": "a.py"})


def test_native_exception_is_converted_to_structured_error(fake_native):
    from cosmya.agent.tools import ToolExecutor

    def boom(root, path):
        raise RuntimeError("disk on fire")

    fake_native.read_file = boom

    executor = ToolExecutor(project_root="/tmp/project")
    result = executor.execute("read_file", {"path": "a.py"})
    assert result["success"] is False
    assert "disk on fire" in result["error"]

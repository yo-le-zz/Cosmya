//! PyO3 entry point: registers Cosmya's six read-only inspection tools as
//! Python functions in the `cosmya._native` module.
//!
//! This file is intentionally thin -- it only translates between Python
//! arguments/return values and the pure-Rust implementations in
//! `tools::filesystem` and `tools::search`. All actual logic (including all
//! sandboxing) lives in those modules.
//!
//! Return type note (pyo3 0.29): functions return `Bound<'py, PyAny>`
//! rather than the older `PyObject`/`Py<PyAny>`. `PyObject` is no longer
//! re-exported by the prelude, and returning it from a `#[pyfunction]`
//! hits an ambiguity in pyo3's newer `IntoPyObject` return-conversion
//! codegen (rustc error E0034, "multiple applicable items in scope" on the
//! generated `.wrap()` call) because `Py<PyAny>` now satisfies more than
//! one internal converter impl. `Bound<'py, PyAny>` avoids that ambiguity
//! entirely and is the type pythonize's `pythonize()` already returns, so
//! no extra conversion is needed either.

use std::path::Path;

use pyo3::prelude::*;
use pythonize::pythonize;

pub mod tools;

use tools::filesystem;
use tools::search;

/// List the immediate contents of a directory inside the project.
#[pyfunction]
#[pyo3(signature = (root, path))]
fn list_directory<'py>(py: Python<'py>, root: &str, path: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = filesystem::list_directory(Path::new(root), path);
    to_py_dict(py, &result)
}

/// Return a bounded recursive directory tree starting at `path`.
#[pyfunction]
#[pyo3(signature = (root, path, max_depth=None))]
fn tree<'py>(
    py: Python<'py>,
    root: &str,
    path: &str,
    max_depth: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let result = filesystem::tree(Path::new(root), path, max_depth);
    to_py_dict(py, &result)
}

/// Read the text content of a single file inside the project.
#[pyfunction]
#[pyo3(signature = (root, path))]
fn read_file<'py>(py: Python<'py>, root: &str, path: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = filesystem::read_file(Path::new(root), path);
    to_py_dict(py, &result)
}

/// Return metadata about a single file or directory.
#[pyfunction]
#[pyo3(signature = (root, path))]
fn file_info<'py>(py: Python<'py>, root: &str, path: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = filesystem::file_info(Path::new(root), path);
    to_py_dict(py, &result)
}

/// Search for a regular-expression pattern across text files under `path`.
#[pyfunction]
#[pyo3(signature = (root, pattern, path, max_results=None))]
fn search_text<'py>(
    py: Python<'py>,
    root: &str,
    pattern: &str,
    path: &str,
    max_results: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let result = search::search_text(Path::new(root), pattern, path, max_results);
    to_py_dict(py, &result)
}

/// Find files under `path` whose name matches a glob pattern.
#[pyfunction]
#[pyo3(signature = (root, glob, path, max_results=None))]
fn search_files<'py>(
    py: Python<'py>,
    root: &str,
    glob: &str,
    path: &str,
    max_results: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let result = search::search_files(Path::new(root), glob, path, max_results);
    to_py_dict(py, &result)
}

/// Convert any `Serialize` result struct into a native Python dict via
/// `pythonize`, so every tool returns a plain, structured Python object
/// (never a formatted string) as required by Cosmya's internal tool
/// protocol.
fn to_py_dict<'py, T: serde::Serialize>(py: Python<'py>, value: &T) -> PyResult<Bound<'py, PyAny>> {
    pythonize(py, value).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

// The #[pymodule] function's Rust identifier determines the compiled
// PyInit_<name> symbol Python's import machinery looks for. pyproject.toml
// configures `module-name = "cosmya._native"`, so Python imports this as
// `cosmya._native` and therefore needs the symbol `PyInit__native` -- i.e.
// this function must be named exactly `_native` (the last path segment),
// NOT `cosmya_native` (that's the separate, unrelated [lib] name used for
// the Rust crate/rlib in Cargo.toml, e.g. for `cargo test`). Using the
// wrong name compiles fine but fails at Python import time with:
// "ImportError: dynamic module does not define module export function
// (PyInit__native)".
#[pymodule]
fn _native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(list_directory, m)?)?;
    m.add_function(wrap_pyfunction!(tree, m)?)?;
    m.add_function(wrap_pyfunction!(read_file, m)?)?;
    m.add_function(wrap_pyfunction!(file_info, m)?)?;
    m.add_function(wrap_pyfunction!(search_text, m)?)?;
    m.add_function(wrap_pyfunction!(search_files, m)?)?;
    Ok(())
}

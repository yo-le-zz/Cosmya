//! Tests for `tools::paths`: the project-root sandbox.
//!
//! These are ordinary `cargo test` unit tests; they build a real temporary
//! directory tree (including real symlinks) on disk for each case rather
//! than asserting on mocked behavior.

use std::fs;
use std::os::unix::fs::symlink;

use cosmya_native::tools::paths::{resolve_safe_path, PathSandboxError};

fn make_project() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("create temp project dir");
    fs::create_dir_all(dir.path().join("src")).unwrap();
    fs::write(dir.path().join("src/main.rs"), "fn main() {}").unwrap();
    fs::create_dir_all(dir.path().join("nested/deep")).unwrap();
    fs::write(dir.path().join("nested/deep/file.txt"), "hello").unwrap();
    dir
}

#[test]
fn allows_a_normal_relative_path_inside_root() {
    let project = make_project();
    let resolved = resolve_safe_path(project.path(), "src/main.rs").unwrap();
    assert!(resolved.ends_with("src/main.rs"));
}

#[test]
fn allows_nested_relative_paths() {
    let project = make_project();
    let resolved = resolve_safe_path(project.path(), "nested/deep/file.txt").unwrap();
    assert!(resolved.ends_with("nested/deep/file.txt"));
}

#[test]
fn allows_root_itself_via_dot() {
    let project = make_project();
    let resolved = resolve_safe_path(project.path(), ".").unwrap();
    assert_eq!(resolved, project.path().canonicalize().unwrap());
}

#[test]
fn rejects_absolute_path() {
    let project = make_project();
    let result = resolve_safe_path(project.path(), "/etc/passwd");
    assert!(matches!(result, Err(PathSandboxError::AbsolutePathRejected(_))));
}

#[test]
fn rejects_simple_parent_traversal() {
    let project = make_project();
    let result = resolve_safe_path(project.path(), "../secret.txt");
    assert!(matches!(result, Err(PathSandboxError::ParentTraversalRejected(_))));
}

#[test]
fn rejects_deep_parent_traversal() {
    let project = make_project();
    let result = resolve_safe_path(project.path(), "../../../../etc/passwd");
    assert!(matches!(result, Err(PathSandboxError::ParentTraversalRejected(_))));
}

#[test]
fn rejects_traversal_hidden_mid_path() {
    let project = make_project();
    // "src/../../outside" still contains a ParentDir component and must be
    // rejected by the syntactic pre-check, without ever touching the
    // filesystem for the escaping portion.
    let result = resolve_safe_path(project.path(), "src/../../outside");
    assert!(matches!(result, Err(PathSandboxError::ParentTraversalRejected(_))));
}

#[test]
fn rejects_nonexistent_path() {
    let project = make_project();
    let result = resolve_safe_path(project.path(), "does/not/exist.txt");
    assert!(matches!(result, Err(PathSandboxError::NotFound(_))));
}

#[test]
fn rejects_symlink_escaping_project_root() {
    let project = make_project();
    // A secret file OUTSIDE the project root...
    let outside = tempfile::tempdir().unwrap();
    let secret_path = outside.path().join("secret.txt");
    fs::write(&secret_path, "top secret").unwrap();

    // ...linked to from INSIDE the project root.
    let link_path = project.path().join("innocuous_link.txt");
    symlink(&secret_path, &link_path).unwrap();

    let result = resolve_safe_path(project.path(), "innocuous_link.txt");
    assert!(
        matches!(result, Err(PathSandboxError::EscapesProjectRoot(_))),
        "expected symlink escape to be rejected, got {result:?}"
    );
}

#[test]
fn rejects_symlinked_directory_escaping_project_root() {
    let project = make_project();
    let outside = tempfile::tempdir().unwrap();
    fs::create_dir_all(outside.path().join("private")).unwrap();
    fs::write(outside.path().join("private/data.txt"), "private data").unwrap();

    let link_dir = project.path().join("linked_dir");
    symlink(outside.path().join("private"), &link_dir).unwrap();

    // Even a path *through* the symlinked directory must be rejected.
    let result = resolve_safe_path(project.path(), "linked_dir/data.txt");
    assert!(matches!(result, Err(PathSandboxError::EscapesProjectRoot(_))));
}

#[test]
fn allows_symlink_that_stays_inside_project_root() {
    let project = make_project();
    // A symlink inside the project pointing to another file *inside* the
    // same project root must be allowed -- only escapes are rejected.
    let link_path = project.path().join("link_to_main.rs");
    symlink(project.path().join("src/main.rs"), &link_path).unwrap();

    let result = resolve_safe_path(project.path(), "link_to_main.rs");
    assert!(result.is_ok());
}

#[test]
fn invalid_root_produces_root_invalid_error() {
    let result = resolve_safe_path(std::path::Path::new("/this/does/not/exist/at/all"), "x");
    assert!(matches!(result, Err(PathSandboxError::RootInvalid(_))));
}

//! Project-root sandboxing.
//!
//! Every other tool module MUST resolve every path it touches through
//! [`resolve_safe_path`] before performing any filesystem operation. This is
//! the single point of enforcement that prevents:
//!
//! * parent-directory traversal (`../../etc/passwd`)
//! * absolute-path escape (`/etc/passwd`)
//! * symlink escape (a symlink inside the project pointing outside it)
//!
//! The strategy is: reject any input path that is itself absolute, join it
//! onto the (canonicalized) project root, canonicalize the *result* (which
//! resolves `..` components and symlinks alike), and then verify the
//! canonical result still lives under the canonical root. Canonicalization
//! is what makes symlink escapes impossible to hide: `fs::canonicalize`
//! follows every symlink component and returns the real, final path.

use std::fmt;
use std::path::{Component, Path, PathBuf};

#[derive(Debug)]
pub enum PathSandboxError {
    AbsolutePathRejected(String),
    ParentTraversalRejected(String),
    EscapesProjectRoot(String),
    NotFound(String),
    RootInvalid(String),
    Io(String),
}

impl fmt::Display for PathSandboxError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PathSandboxError::AbsolutePathRejected(p) => {
                write!(f, "Absolute paths are not allowed: {p}")
            }
            PathSandboxError::ParentTraversalRejected(p) => {
                write!(f, "Path escapes the project root via '..': {p}")
            }
            PathSandboxError::EscapesProjectRoot(p) => {
                write!(f, "Resolved path escapes the project root: {p}")
            }
            PathSandboxError::NotFound(p) => write!(f, "Path does not exist: {p}"),
            PathSandboxError::RootInvalid(p) => write!(f, "Invalid project root: {p}"),
            PathSandboxError::Io(msg) => write!(f, "I/O error while resolving path: {msg}"),
        }
    }
}

impl std::error::Error for PathSandboxError {}

/// Resolve `relative` against `root`, guaranteeing the result is inside
/// `root` even in the presence of symlinks.
///
/// `relative` must be a relative path (no leading `/`) and must not contain
/// a `..` component that would (syntactically) escape `root` before
/// canonicalization is even attempted -- this gives an early, clear error
/// message on the most common misuse rather than relying solely on the
/// canonicalization check.
///
/// The target does not need to exist for this function to reject an
/// unsafe input, but a non-existent path (after a safe, syntactic join)
/// currently returns [`PathSandboxError::NotFound`] since none of Cosmya's
/// read-only tools have a legitimate reason to resolve a path that isn't
/// there.
pub fn resolve_safe_path(root: &Path, relative: &str) -> Result<PathBuf, PathSandboxError> {
    let canonical_root = root
        .canonicalize()
        .map_err(|e| PathSandboxError::RootInvalid(format!("{}: {e}", root.display())))?;

    let requested = Path::new(relative);

    if requested.is_absolute() {
        return Err(PathSandboxError::AbsolutePathRejected(relative.to_string()));
    }

    // Syntactic pre-check: reject any `..` component outright. This also
    // catches Windows-style drive-relative oddities defensively, though
    // Cosmya targets Linux only.
    for component in requested.components() {
        match component {
            Component::ParentDir => {
                return Err(PathSandboxError::ParentTraversalRejected(
                    relative.to_string(),
                ))
            }
            Component::Prefix(_) | Component::RootDir => {
                return Err(PathSandboxError::AbsolutePathRejected(relative.to_string()))
            }
            _ => {}
        }
    }

    let joined = canonical_root.join(requested);

    // Canonicalize the joined path. This resolves any symlink components,
    // which is what actually defeats a malicious repository containing a
    // symlink that points outside the project root.
    let canonical_target = joined.canonicalize().map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            PathSandboxError::NotFound(relative.to_string())
        } else {
            PathSandboxError::Io(format!("{}: {e}", joined.display()))
        }
    })?;

    if !canonical_target.starts_with(&canonical_root) {
        return Err(PathSandboxError::EscapesProjectRoot(relative.to_string()));
    }

    Ok(canonical_target)
}

/// Like [`resolve_safe_path`] but permits the target to not yet exist,
/// still fully rejecting traversal/absolute-path/symlink escape on every
/// component that DOES exist. Used only where a tool must operate on a
/// path that is allowed to be missing (currently unused by any read-only
/// tool, but kept available and tested for future tools that need it).
pub fn resolve_safe_path_allow_missing(
    root: &Path,
    relative: &str,
) -> Result<PathBuf, PathSandboxError> {
    match resolve_safe_path(root, relative) {
        Ok(p) => Ok(p),
        Err(PathSandboxError::NotFound(_)) => {
            // Walk up the path until we find an existing ancestor, verify
            // *that* ancestor is safely inside root, then re-append the
            // missing tail syntactically (already proven traversal-free by
            // the component check in resolve_safe_path above).
            let canonical_root = root
                .canonicalize()
                .map_err(|e| PathSandboxError::RootInvalid(format!("{}: {e}", root.display())))?;
            let requested = Path::new(relative);
            let mut existing = canonical_root.clone();
            let mut tail = PathBuf::new();
            let mut found_existing_ancestor = false;

            for component in requested.components() {
                let candidate = existing.join(component);
                if !found_existing_ancestor && candidate.exists() {
                    existing = candidate;
                } else {
                    found_existing_ancestor = true;
                    tail.push(component);
                }
            }

            let canonical_existing = existing
                .canonicalize()
                .map_err(|e| PathSandboxError::Io(e.to_string()))?;
            if !canonical_existing.starts_with(&canonical_root) {
                return Err(PathSandboxError::EscapesProjectRoot(relative.to_string()));
            }
            Ok(canonical_existing.join(tail))
        }
        Err(other) => Err(other),
    }
}

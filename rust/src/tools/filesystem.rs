//! Read-only filesystem inspection tools.
//!
//! Every public function here takes the already-untrusted `root` and a
//! caller-supplied relative `path`, resolves it through
//! [`super::paths::resolve_safe_path`], and only then touches the
//! filesystem. Nothing in this module ever writes, deletes, or executes
//! anything.

use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::UNIX_EPOCH;

use serde::Serialize;

use super::paths::{resolve_safe_path, PathSandboxError};

/// Files larger than this are not read in full; a truncated prefix plus a
/// notice is returned instead, so a single huge file cannot exhaust the
/// AI's context window or Cosmya's memory.
pub(crate) const MAX_READ_BYTES: u64 = 512 * 1024; // 512 KiB

/// Files larger than this are skipped entirely during text search (rather
/// than truncated), since a partial match inside a multi-megabyte file is
/// rarely useful and scanning it fully would be wasteful.
pub(crate) const MAX_SEARCH_FILE_BYTES: u64 = 2 * 1024 * 1024; // 2 MiB

/// Maximum number of entries returned by `list_directory` in one call.
const MAX_LIST_ENTRIES: usize = 2000;

/// Maximum recursion depth for `tree` if the caller does not specify one.
const DEFAULT_TREE_DEPTH: usize = 5;
const MAX_TREE_DEPTH: usize = 12;

/// Maximum number of nodes rendered by `tree`, regardless of depth, to
/// bound output size on very wide/large repositories.
const MAX_TREE_NODES: usize = 5000;

#[derive(Serialize)]
pub struct DirEntryInfo {
    pub name: String,
    pub is_dir: bool,
    pub is_symlink: bool,
}

#[derive(Serialize)]
pub struct ListDirectoryResult {
    pub success: bool,
    pub path: String,
    pub entries: Vec<DirEntryInfo>,
    pub truncated: bool,
    pub error: Option<String>,
}

pub fn list_directory(root: &Path, path: &str) -> ListDirectoryResult {
    let resolved = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => return list_directory_error(path, e),
    };

    let read_dir = match fs::read_dir(&resolved) {
        Ok(rd) => rd,
        Err(e) => {
            return ListDirectoryResult {
                success: false,
                path: path.to_string(),
                entries: vec![],
                truncated: false,
                error: Some(format!("Could not list directory: {e}")),
            }
        }
    };

    let mut entries = Vec::new();
    let mut truncated = false;
    for entry in read_dir.flatten() {
        if entries.len() >= MAX_LIST_ENTRIES {
            truncated = true;
            break;
        }
        let file_type = match entry.file_type() {
            Ok(ft) => ft,
            Err(_) => continue,
        };
        entries.push(DirEntryInfo {
            name: entry.file_name().to_string_lossy().to_string(),
            is_dir: file_type.is_dir(),
            is_symlink: file_type.is_symlink(),
        });
    }
    entries.sort_by(|a, b| a.name.cmp(&b.name));

    ListDirectoryResult {
        success: true,
        path: path.to_string(),
        entries,
        truncated,
        error: None,
    }
}

fn list_directory_error(path: &str, e: PathSandboxError) -> ListDirectoryResult {
    ListDirectoryResult {
        success: false,
        path: path.to_string(),
        entries: vec![],
        truncated: false,
        error: Some(e.to_string()),
    }
}

#[derive(Serialize)]
pub struct TreeResult {
    pub success: bool,
    pub path: String,
    pub tree: String,
    pub truncated: bool,
    pub error: Option<String>,
}

pub fn tree(root: &Path, path: &str, max_depth: Option<usize>) -> TreeResult {
    let depth = max_depth
        .unwrap_or(DEFAULT_TREE_DEPTH)
        .min(MAX_TREE_DEPTH)
        .max(1);

    let resolved = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => {
            return TreeResult {
                success: false,
                path: path.to_string(),
                tree: String::new(),
                truncated: false,
                error: Some(e.to_string()),
            }
        }
    };

    let mut output = String::new();
    let mut node_count = 0usize;
    let mut truncated = false;
    build_tree_lines(
        &resolved,
        0,
        depth,
        &mut output,
        &mut node_count,
        &mut truncated,
    );

    TreeResult {
        success: true,
        path: path.to_string(),
        tree: output,
        truncated,
        error: None,
    }
}

fn build_tree_lines(
    dir: &Path,
    current_depth: usize,
    max_depth: usize,
    out: &mut String,
    node_count: &mut usize,
    truncated: &mut bool,
) {
    if current_depth >= max_depth || *truncated {
        return;
    }
    let mut children: Vec<_> = match fs::read_dir(dir) {
        Ok(rd) => rd.flatten().collect(),
        Err(_) => return,
    };
    children.sort_by_key(|e| e.file_name());

    for entry in children {
        if *node_count >= MAX_TREE_NODES {
            *truncated = true;
            out.push_str("... (truncated: too many entries)\n");
            return;
        }
        let file_type = match entry.file_type() {
            Ok(ft) => ft,
            Err(_) => continue,
        };
        let indent = "  ".repeat(current_depth);
        let name = entry.file_name().to_string_lossy().to_string();
        if file_type.is_dir() {
            out.push_str(&format!("{indent}{name}/\n"));
            *node_count += 1;
            build_tree_lines(
                &entry.path(),
                current_depth + 1,
                max_depth,
                out,
                node_count,
                truncated,
            );
        } else {
            out.push_str(&format!("{indent}{name}\n"));
            *node_count += 1;
        }
    }
}

#[derive(Serialize)]
pub struct ReadFileResult {
    pub success: bool,
    pub path: String,
    pub content: Option<String>,
    pub truncated: bool,
    pub is_binary: bool,
    pub error: Option<String>,
}

pub fn read_file(root: &Path, path: &str) -> ReadFileResult {
    let resolved = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => {
            return ReadFileResult {
                success: false,
                path: path.to_string(),
                content: None,
                truncated: false,
                is_binary: false,
                error: Some(e.to_string()),
            }
        }
    };

    if resolved.is_dir() {
        return ReadFileResult {
            success: false,
            path: path.to_string(),
            content: None,
            truncated: false,
            is_binary: false,
            error: Some("Path is a directory, not a file.".to_string()),
        };
    }

    let mut file = match fs::File::open(&resolved) {
        Ok(f) => f,
        Err(e) => {
            return ReadFileResult {
                success: false,
                path: path.to_string(),
                content: None,
                truncated: false,
                is_binary: false,
                error: Some(format!("Could not open file: {e}")),
            }
        }
    };

    let mut buffer = vec![0u8; 0];
    let cap = (MAX_READ_BYTES + 1) as usize;
    buffer.reserve(cap.min(8 * 1024 * 1024));
    let mut limited_reader = (&mut file).take(MAX_READ_BYTES + 1);
    if let Err(e) = limited_reader.read_to_end(&mut buffer) {
        return ReadFileResult {
            success: false,
            path: path.to_string(),
            content: None,
            truncated: false,
            is_binary: false,
            error: Some(format!("Could not read file: {e}")),
        };
    }

    if looks_binary(&buffer) {
        return ReadFileResult {
            success: false,
            path: path.to_string(),
            content: None,
            truncated: false,
            is_binary: true,
            error: Some("File appears to be binary and was not read as text.".to_string()),
        };
    }

    let truncated = buffer.len() as u64 > MAX_READ_BYTES;
    if truncated {
        buffer.truncate(MAX_READ_BYTES as usize);
    }

    let content = String::from_utf8_lossy(&buffer).to_string();

    ReadFileResult {
        success: true,
        path: path.to_string(),
        content: Some(content),
        truncated,
        is_binary: false,
        error: None,
    }
}

/// Heuristic binary detection: a NUL byte anywhere in the first chunk is a
/// strong signal of a binary file. This mirrors the heuristic `git` itself
/// uses for `core.autocrlf`/diff binary detection.
fn looks_binary(bytes: &[u8]) -> bool {
    let sample_len = bytes.len().min(8000);
    bytes[..sample_len].contains(&0u8)
}

#[derive(Serialize)]
pub struct FileInfoResult {
    pub success: bool,
    pub path: String,
    pub size_bytes: Option<u64>,
    pub is_dir: Option<bool>,
    pub is_symlink: Option<bool>,
    pub is_binary: Option<bool>,
    pub modified_unix: Option<u64>,
    pub error: Option<String>,
}

pub fn file_info(root: &Path, path: &str) -> FileInfoResult {
    let resolved = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => {
            return FileInfoResult {
                success: false,
                path: path.to_string(),
                size_bytes: None,
                is_dir: None,
                is_symlink: None,
                is_binary: None,
                modified_unix: None,
                error: Some(e.to_string()),
            }
        }
    };

    let symlink_metadata = match fs::symlink_metadata(&resolved) {
        Ok(m) => m,
        Err(e) => {
            return FileInfoResult {
                success: false,
                path: path.to_string(),
                size_bytes: None,
                is_dir: None,
                is_symlink: None,
                is_binary: None,
                modified_unix: None,
                error: Some(format!("Could not stat path: {e}")),
            }
        }
    };

    let metadata = fs::metadata(&resolved).unwrap_or(symlink_metadata.clone());
    let is_binary = if metadata.is_file() {
        let mut buf = vec![0u8; 8000.min(metadata.len() as usize)];
        if let Ok(mut f) = fs::File::open(&resolved) {
            let n = f.read(&mut buf).unwrap_or(0);
            Some(looks_binary(&buf[..n]))
        } else {
            None
        }
    } else {
        None
    };

    let modified_unix = metadata
        .modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs());

    FileInfoResult {
        success: true,
        path: path.to_string(),
        size_bytes: Some(metadata.len()),
        is_dir: Some(metadata.is_dir()),
        is_symlink: Some(symlink_metadata.file_type().is_symlink()),
        is_binary,
        modified_unix,
        error: None,
    }
}

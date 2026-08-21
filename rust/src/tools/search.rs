//! Read-only search tools: regex text search and glob-based file-name search.
//!
//! Both walk the filesystem starting at a sandboxed root (never outside the
//! project root -- enforced by resolving the starting path through
//! [`super::paths::resolve_safe_path`] before any traversal begins) and are
//! bounded in the number of results they return so a huge or adversarial
//! repository cannot exhaust memory or flood the AI's context window.
//! `.gitignore`-style ignore rules are respected via the `ignore` crate so
//! generated/vendored directories (e.g. `node_modules`, `.git`) are skipped
//! by default, mirroring how a human reviewer would explore the project.

use std::path::Path;

use globset::{Glob, GlobSetBuilder};
use ignore::WalkBuilder;
use regex::Regex;
use serde::Serialize;

use super::filesystem::MAX_SEARCH_FILE_BYTES;
use super::paths::resolve_safe_path;

const DEFAULT_MAX_TEXT_RESULTS: usize = 100;
const MAX_TEXT_RESULTS_CAP: usize = 500;
const DEFAULT_MAX_FILE_RESULTS: usize = 200;
const MAX_FILE_RESULTS_CAP: usize = 1000;
const MAX_FILES_SCANNED: usize = 20_000;

#[derive(Serialize)]
pub struct TextMatch {
    pub file: String,
    pub line: usize,
    pub text: String,
}

#[derive(Serialize)]
pub struct SearchTextResult {
    pub success: bool,
    pub matches: Vec<TextMatch>,
    pub truncated: bool,
    pub error: Option<String>,
}

pub fn search_text(
    root: &Path,
    pattern: &str,
    path: &str,
    max_results: Option<usize>,
) -> SearchTextResult {
    let limit = max_results
        .unwrap_or(DEFAULT_MAX_TEXT_RESULTS)
        .min(MAX_TEXT_RESULTS_CAP)
        .max(1);

    let regex = match Regex::new(pattern) {
        Ok(r) => r,
        Err(e) => {
            return SearchTextResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(format!("Invalid regular expression: {e}")),
            }
        }
    };

    let start_dir = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => {
            return SearchTextResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(e.to_string()),
            }
        }
    };
    // `root` itself is already trusted (it was canonicalized to build
    // `start_dir` via resolve_safe_path); we re-derive it only for
    // producing project-root-relative match paths in the output.
    let canonical_root = match root.canonicalize() {
        Ok(p) => p,
        Err(e) => {
            return SearchTextResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(format!("Invalid project root: {e}")),
            }
        }
    };

    let mut matches = Vec::new();
    let mut truncated = false;
    let mut files_scanned = 0usize;

    for entry in WalkBuilder::new(&start_dir).hidden(false).build() {
        if matches.len() >= limit {
            truncated = true;
            break;
        }
        if files_scanned >= MAX_FILES_SCANNED {
            truncated = true;
            break;
        }
        let Ok(entry) = entry else { continue };
        // Defense in depth: even though WalkBuilder was rooted at a path we
        // already proved is inside the sandbox, re-verify every visited
        // entry never escapes root (guards against a symlinked directory
        // encountered mid-walk).
        let Ok(canonical_entry) = entry.path().canonicalize() else {
            continue;
        };
        if !canonical_entry.starts_with(&canonical_root) {
            continue;
        }
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        files_scanned += 1;

        let Ok(bytes) = std::fs::read(entry.path()) else {
            continue;
        };
        if bytes.len() as u64 > MAX_SEARCH_FILE_BYTES {
            continue;
        }
        if bytes[..bytes.len().min(8000)].contains(&0u8) {
            continue; // skip binary files
        }
        let text = String::from_utf8_lossy(&bytes);
        let relative_display = canonical_entry
            .strip_prefix(&canonical_root)
            .unwrap_or(&canonical_entry)
            .display()
            .to_string();

        for (line_number, line) in text.lines().enumerate() {
            if regex.is_match(line) {
                matches.push(TextMatch {
                    file: relative_display.clone(),
                    line: line_number + 1,
                    text: line.chars().take(500).collect(),
                });
                if matches.len() >= limit {
                    truncated = true;
                    break;
                }
            }
        }
    }

    SearchTextResult {
        success: true,
        matches,
        truncated,
        error: None,
    }
}

#[derive(Serialize)]
pub struct SearchFilesResult {
    pub success: bool,
    pub matches: Vec<String>,
    pub truncated: bool,
    pub error: Option<String>,
}

pub fn search_files(
    root: &Path,
    glob_pattern: &str,
    path: &str,
    max_results: Option<usize>,
) -> SearchFilesResult {
    let limit = max_results
        .unwrap_or(DEFAULT_MAX_FILE_RESULTS)
        .min(MAX_FILE_RESULTS_CAP)
        .max(1);

    let glob = match Glob::new(glob_pattern) {
        Ok(g) => g,
        Err(e) => {
            return SearchFilesResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(format!("Invalid glob pattern: {e}")),
            }
        }
    };
    let mut builder = GlobSetBuilder::new();
    builder.add(glob);
    let globset = match builder.build() {
        Ok(g) => g,
        Err(e) => {
            return SearchFilesResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(format!("Invalid glob pattern: {e}")),
            }
        }
    };

    let start_dir = match resolve_safe_path(root, path) {
        Ok(p) => p,
        Err(e) => {
            return SearchFilesResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(e.to_string()),
            }
        }
    };
    let canonical_root = match root.canonicalize() {
        Ok(p) => p,
        Err(e) => {
            return SearchFilesResult {
                success: false,
                matches: vec![],
                truncated: false,
                error: Some(format!("Invalid project root: {e}")),
            }
        }
    };

    let mut matches = Vec::new();
    let mut truncated = false;
    let mut files_scanned = 0usize;

    for entry in WalkBuilder::new(&start_dir).hidden(false).build() {
        if matches.len() >= limit {
            truncated = true;
            break;
        }
        if files_scanned >= MAX_FILES_SCANNED {
            truncated = true;
            break;
        }
        let Ok(entry) = entry else { continue };
        let Ok(canonical_entry) = entry.path().canonicalize() else {
            continue;
        };
        if !canonical_entry.starts_with(&canonical_root) {
            continue;
        }
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        files_scanned += 1;

        let relative_display = canonical_entry
            .strip_prefix(&canonical_root)
            .unwrap_or(&canonical_entry)
            .display()
            .to_string();

        if globset.is_match(&relative_display) || globset.is_match(entry.file_name()) {
            matches.push(relative_display);
        }
    }

    SearchFilesResult {
        success: true,
        matches,
        truncated,
        error: None,
    }
}

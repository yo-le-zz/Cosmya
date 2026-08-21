use std::fs;

use cosmya_native::tools::filesystem::{file_info, list_directory, read_file, tree};

fn make_project() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir_all(dir.path().join("src")).unwrap();
    fs::write(dir.path().join("src/main.rs"), "fn main() {}\n").unwrap();
    fs::create_dir_all(dir.path().join("src/nested")).unwrap();
    fs::write(dir.path().join("src/nested/deep.rs"), "// deep\n").unwrap();
    fs::write(dir.path().join("README.md"), "# Project\n").unwrap();
    dir
}

#[test]
fn list_directory_returns_entries_sorted() {
    let project = make_project();
    let result = list_directory(project.path(), ".");
    assert!(result.success);
    let names: Vec<_> = result.entries.iter().map(|e| e.name.clone()).collect();
    let mut sorted = names.clone();
    sorted.sort();
    assert_eq!(names, sorted);
    assert!(names.contains(&"src".to_string()));
    assert!(names.contains(&"README.md".to_string()));
}

#[test]
fn list_directory_rejects_traversal() {
    let project = make_project();
    let result = list_directory(project.path(), "../");
    assert!(!result.success);
    assert!(result.error.is_some());
}

#[test]
fn read_file_returns_content() {
    let project = make_project();
    let result = read_file(project.path(), "src/main.rs");
    assert!(result.success);
    assert_eq!(result.content.unwrap(), "fn main() {}\n");
    assert!(!result.is_binary);
    assert!(!result.truncated);
}

#[test]
fn read_file_rejects_directory() {
    let project = make_project();
    let result = read_file(project.path(), "src");
    assert!(!result.success);
}

#[test]
fn read_file_rejects_traversal() {
    let project = make_project();
    let result = read_file(project.path(), "../../etc/passwd");
    assert!(!result.success);
}

#[test]
fn read_file_detects_binary_content() {
    let project = make_project();
    fs::write(project.path().join("data.bin"), [0u8, 1, 2, 0, 255]).unwrap();
    let result = read_file(project.path(), "data.bin");
    assert!(!result.success);
    assert!(result.is_binary);
    assert!(result.content.is_none());
}

#[test]
fn read_file_truncates_oversized_files() {
    let project = make_project();
    // 512 KiB limit -- write 600 KiB of 'a's.
    let big_content = "a".repeat(600 * 1024);
    fs::write(project.path().join("big.txt"), &big_content).unwrap();
    let result = read_file(project.path(), "big.txt");
    assert!(result.success);
    assert!(result.truncated);
    assert!(result.content.unwrap().len() < big_content.len());
}

#[test]
fn tree_includes_nested_files_within_depth() {
    let project = make_project();
    let result = tree(project.path(), ".", Some(5));
    assert!(result.success);
    assert!(result.tree.contains("main.rs"));
    assert!(result.tree.contains("deep.rs"));
}

#[test]
fn tree_respects_max_depth() {
    let project = make_project();
    let shallow = tree(project.path(), ".", Some(1));
    assert!(shallow.success);
    // At depth 1 we should see "src/" but not descend into it far enough
    // to reach the doubly-nested "deep.rs".
    assert!(!shallow.tree.contains("deep.rs"));
}

#[test]
fn file_info_reports_size_and_type() {
    let project = make_project();
    let result = file_info(project.path(), "README.md");
    assert!(result.success);
    assert_eq!(result.is_dir, Some(false));
    assert_eq!(result.size_bytes, Some(10));
}

#[test]
fn file_info_on_directory_reports_is_dir_true() {
    let project = make_project();
    let result = file_info(project.path(), "src");
    assert!(result.success);
    assert_eq!(result.is_dir, Some(true));
}

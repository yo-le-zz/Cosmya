use std::fs;

use cosmya_native::tools::search::{search_files, search_text};

fn make_project() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir_all(dir.path().join("src")).unwrap();
    fs::write(
        dir.path().join("src/auth.py"),
        "password = get_password()\nAPI_KEY = 'sk-hardcoded-secret'\n",
    )
    .unwrap();
    fs::write(
        dir.path().join("src/util.py"),
        "def helper():\n    return 1\n",
    )
    .unwrap();
    fs::create_dir_all(dir.path().join("tests")).unwrap();
    fs::write(
        dir.path().join("tests/test_util.py"),
        "def test_helper():\n    pass\n",
    )
    .unwrap();
    dir
}

#[test]
fn search_text_finds_matches_with_line_numbers() {
    let project = make_project();
    let result = search_text(project.path(), "password", ".", None);
    assert!(result.success);
    assert_eq!(result.matches.len(), 1);
    assert_eq!(result.matches[0].line, 1);
    assert!(result.matches[0].file.contains("auth.py"));
}

#[test]
fn search_text_respects_max_results() {
    let project = make_project();
    for i in 0..20 {
        fs::write(project.path().join(format!("file_{i}.txt")), "needle\n").unwrap();
    }
    let result = search_text(project.path(), "needle", ".", Some(5));
    assert!(result.success);
    assert_eq!(result.matches.len(), 5);
    assert!(result.truncated);
}

#[test]
fn search_text_rejects_invalid_regex() {
    let project = make_project();
    let result = search_text(project.path(), "([unclosed", ".", None);
    assert!(!result.success);
    assert!(result.error.is_some());
}

#[test]
fn search_text_rejects_traversal_root() {
    let project = make_project();
    let result = search_text(project.path(), "password", "../../", None);
    assert!(!result.success);
}

#[test]
fn search_files_matches_glob_pattern() {
    let project = make_project();
    let result = search_files(project.path(), "*.py", ".", None);
    assert!(result.success);
    assert_eq!(result.matches.len(), 3);
}

#[test]
fn search_files_matches_scoped_to_subdirectory() {
    let project = make_project();
    let result = search_files(project.path(), "*.py", "tests", None);
    assert!(result.success);
    assert_eq!(result.matches.len(), 1);
    assert!(result.matches[0].contains("test_util.py"));
}

#[test]
fn search_files_respects_max_results() {
    let project = make_project();
    for i in 0..10 {
        fs::write(project.path().join(format!("gen_{i}.gen")), "x").unwrap();
    }
    let result = search_files(project.path(), "*.gen", ".", Some(3));
    assert!(result.success);
    assert_eq!(result.matches.len(), 3);
    assert!(result.truncated);
}

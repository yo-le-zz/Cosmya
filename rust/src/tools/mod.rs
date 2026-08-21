//! The six read-only, sandboxed inspection tools Cosmya exposes to the AI.
//!
//! There is intentionally no module here for writing, deleting, or
//! executing anything -- Cosmya's Rust layer is read-only by construction.

pub mod filesystem;
pub mod paths;
pub mod search;

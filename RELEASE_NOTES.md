# Cosmya v0.1.0 — Release Notes

**First public release.** Cosmya is an AI-powered, **read-only** code auditor
for Linux. It analyzes a codebase with the help of a large language model
and reports security vulnerabilities, bugs, architectural weaknesses, and
other meaningful issues — without ever writing, deleting, or executing
anything in the audited project.

- Repository: https://github.com/yo-le-zz/Cosmya
- Website: https://cosmya.pages.dev/
- License: [YO-LE-ZZ COMMUNITY LICENSE v1.0](./LICENSE)

---

## Highlights

- **Four AI providers**: OpenAI, Google Gemini, Anthropic Claude, and local
  Ollama, behind one unified provider abstraction with automatic model
  discovery — no hardcoded model lists.
- **Encrypted credential storage**: API keys are protected with an
  Argon2id-derived key and AES-256-GCM authenticated encryption. Your
  password is never written to disk, only a one-way verifier.
- **Rust-backed sandboxed inspection engine**: filesystem tools
  (`list_directory`, `tree`, `read_file`, `search_text`, `search_files`,
  `file_info`) are implemented in Rust and exposed to Python through a
  native PyO3 extension. Every path is canonicalized and checked against
  the project root, defeating path traversal, absolute-path escape, and
  symlink escape — even with a maliciously crafted repository.
- **No generic shell tool.** The AI is given exactly those six read-only
  tools. There is no `run_command`-style tool and no way for it to execute
  arbitrary commands.
- **Prompt-injection aware.** Repository content is explicitly treated as
  untrusted data, never as instructions, in Cosmya's system prompt.
- **Strict structured output.** The AI's final report is validated against
  a Pydantic schema before anything is rendered; malformed responses are
  never trusted or displayed as-is.
- **Polished terminal UI** built with Typer, Rich, and Questionary — fully
  terminal-based, no web UI or desktop app.

## Installation

Linux x86_64 (amd64) only, for this release.

```bash
curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Cosmya/main/install.sh | bash
```

Or download `cosmya_0.1.0_amd64.deb` from this release and install it
manually:

```bash
sudo apt install ./cosmya_0.1.0_amd64.deb
```

## Usage

```bash
cosmya --version
cosmya config      # configure a provider, pick a model, set preferences
cosmya audit <path>
```

## Fixed in this release

- **Model selection crash (`asyncio.run() cannot be called from a running
  event loop`)**: selecting **2. Model** from the configuration menu after
  configuring at least one API-key-based provider crashed with a
  `RuntimeError`. The credential-vault password prompt was being triggered
  from inside the async model-discovery routine, which was itself already
  running inside an active `asyncio` event loop — and `questionary`'s
  synchronous `.ask()` tries to start its own event loop internally, which
  Python does not allow while one is already running.

  Fixed by asking for the vault password once, up front, in the normal
  (non-async) menu code, before the async model-discovery loop starts —
  matching the pattern already used correctly elsewhere (provider
  connectivity testing). This also avoids the password prompt visually
  fighting with the "Querying configured providers..." spinner for control
  of the terminal.

## Known limitations

- Linux x86_64 only. No Windows, macOS, or ARM packages yet.
- Cosmya only audits; it never proposes or applies code changes.
- Ollama support requires a locally running Ollama daemon with models
  already pulled (`ollama pull <model>`) — Cosmya does not install or
  manage Ollama itself.
- Audit quality depends on the configured model and the project's size
  relative to that model's context window.

## Checksums

A `cosmya_0.1.0_amd64.deb.sha256` file is published alongside the `.deb`
asset on this release. `install.sh` verifies it automatically; to check it
by hand:

```bash
sha256sum -c cosmya_0.1.0_amd64.deb.sha256
```

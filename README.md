# Cosmya

**Cosmya** is an AI-powered, **read-only** code auditor. It inspects an entire
codebase with the help of a large language model and reports security
vulnerabilities, bugs, logical errors, architectural weaknesses, performance
problems, maintainability issues, bad practices, suspicious code, reliability
risks, and dependency-related risks when detectable.

> **Cosmya never modifies the code it audits.** It has no write, delete, or
> execute capability against your project -- only bounded, sandboxed, read-only
> inspection tools.

- Repository: https://github.com/yo-le-zz/Cosmya
- Website: https://cosmya.pages.dev/
- License: [YO-LE-ZZ COMMUNITY LICENSE v1.0](./LICENSE)
- Author: yolezz

---

## Features

- **Terminal-only**, polished CLI built with [Typer](https://typer.tiangolo.com/)
  and [Rich](https://rich.readthedocs.io/) -- no web UI, no desktop GUI.
- **Four AI providers**: OpenAI, Google Gemini, Anthropic Claude, and local
  Ollama models, behind a single unified provider abstraction.
- **Automatic model discovery** -- Cosmya queries each configured provider for
  the models actually available to your account; nothing is hardcoded.
- **Encrypted credential storage** -- API keys are protected with
  Argon2id-derived, AES-256-GCM-encrypted storage. Your password is never
  persisted.
- **Rust-backed sandboxed inspection engine** -- filesystem tools are
  implemented in Rust (via PyO3) and strictly confined to the project root,
  with defenses against path traversal, absolute-path escape, and symlink
  escape.
- **No generic shell tool.** The AI can only call six predefined, read-only,
  schema-validated tools. It cannot invent or run arbitrary commands.
- **Strict structured output.** The AI's final answer is validated against a
  Pydantic schema before anything is rendered; malformed output is never
  trusted.
- **Prompt-injection aware.** Repository content is explicitly treated as
  untrusted data, never as instructions, in Cosmya's system prompt.

## Architecture

Cosmya is split into three parts:

```
Python (orchestration)        Rust (inspection engine)
├── CLI (Typer + Rich)        ├── path sandboxing
├── AI provider abstraction   ├── list_directory / tree
├── agent loop / tool calling ├── read_file / file_info
├── audit schema + rendering  └── search_text / search_files
└── encrypted config/creds        (exposed to Python via PyO3)
```

Python is responsible for CLI orchestration, configuration, AI provider
communication, the agent's tool-calling loop, JSON validation, and terminal
rendering. Rust is used **only** for low-level, performance-sensitive,
security-critical filesystem inspection, exposed to Python as a native
extension module (`cosmya._native`) via [PyO3](https://pyo3.rs/) -- there is
no subprocess, stdin/stdout, or temp-file bridge between the two.

```
Python  ->  PyO3 native extension  ->  Rust tools
```

### Supported AI providers

| Provider | API key required | Notes |
|---|---|---|
| OpenAI | Yes | Direct HTTPS calls to `api.openai.com`, no SDK dependency |
| Google Gemini | Yes | Direct HTTPS calls to the Generative Language API |
| Anthropic Claude | Yes | Direct HTTPS calls to `api.anthropic.com` |
| Ollama | No | Talks to a local Ollama daemon (default `http://localhost:11434`) |

### Security model

- **Read-only, always.** Rust's filesystem tools implement no write, delete,
  rename, or execute operation. There is no path in the codebase for the AI
  to alter the audited project.
- **Project-root sandbox.** Every filesystem tool resolves its path argument
  through a single Rust function that canonicalizes the path and verifies it
  remains under the project root -- this defeats `../` traversal, absolute
  paths, and symlinks that point outside the sandbox, even in a maliciously
  crafted repository.
- **No shell access.** The AI is given exactly six tools
  (`list_directory`, `tree`, `read_file`, `search_text`, `search_files`,
  `file_info`). There is no `run_command`-style tool and never will be.
- **Untrusted AI, untrusted repository.** Both the model's output and the
  audited repository's content are treated as untrusted. The model's final
  answer is only ever used after it is validated against a strict Pydantic
  schema; repository content is explicitly instructed to be treated as
  inert data, not instructions (defense against prompt injection).
- **Encrypted credentials.** API keys are encrypted with AES-256-GCM under a
  key derived from your password via Argon2id. The password itself is never
  written to disk; only a one-way verifier is stored, used solely to confirm
  a password attempt is correct.
- **Bounded resource use.** File reads, search results, and tree depth are
  all capped so a huge or adversarial repository cannot exhaust memory or
  flood the AI's context window.

## Installation (Linux x86_64)

Cosmya currently ships for **Linux x86_64 (amd64)** only.

### One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Cosmya/main/install.sh | bash
```

This downloads the latest `.deb` from
[GitHub Releases](https://github.com/yo-le-zz/Cosmya/releases), verifies its
checksum, and installs it. It does **not** compile anything and does **not**
require Rust, Python build tools, uv, or maturin on your machine.

### Manual install

Download the latest `cosmya_<version>_amd64.deb` from
[GitHub Releases](https://github.com/yo-le-zz/Cosmya/releases) and run:

```bash
sudo apt install ./cosmya_<version>_amd64.deb
```

### Uninstall

```bash
sudo apt remove cosmya
```

## Usage

```bash
cosmya --version         # show version and metadata
cosmya --help             # show all commands
cosmya config              # open the interactive configuration menu
cosmya audit <path>        # run a read-only audit of a project directory
```

### Configuration flow

```
cosmya config
├── 1. Providers     -> configure OpenAI / Gemini / Claude / Ollama
├── 2. Model         -> discover and select a model from configured providers
├── 3. Preferences   -> custom instructions injected into every audit
└── 0. Exit
```

Configuring a provider walks you through: entering an API key (masked, never
printed), setting or entering your credential protection password, encrypting
and storing the key, testing connectivity, and discovering available models.

### Running an audit

```bash
cosmya audit /path/to/your/project
```

Cosmya will ask for your credential password (unless
`COSMYA_VAULT_PASSWORD` is set in the environment), then run the configured
model through an agent loop: it explores the project with the sandboxed Rust
tools, investigates files relevant to security and correctness, and returns
a validated JSON report that Cosmya renders as a readable terminal report
with colored severity levels (critical/high/medium/low/info).

## Development setup

Requirements: Python >= 3.11, [uv](https://docs.astral.sh/uv/), Rust stable,
Cargo, [maturin](https://www.maturin.rs/) (installed automatically by `uv`
when building), `dpkg-dev` (for packaging).

```bash
git clone https://github.com/yo-le-zz/Cosmya
cd Cosmya

# Python-only development (native Rust tools unavailable until built):
uv venv .venv && source .venv/bin/activate
uv pip install -e . --group dev
python -m pytest tests/python/ -q

# Build the Rust native extension into the active venv:
cd rust && cargo test --release && cd ..
uv pip install -e .   # builds rust/ via maturin and installs cosmya._native
python -c "import cosmya._native"   # should succeed once built
```

### Running tests

```bash
# Python
python -m pytest tests/python/ -q

# Rust
cd rust && cargo test --release
```

### Building the .deb locally

```bash
./build.sh
```

This runs the full Python and Rust test suites, builds the Rust extension in
release mode, assembles a self-contained runtime environment, and produces
`dist/cosmya_<version>_amd64.deb`. The script fails immediately (`set -euo
pipefail`) on any error and never silently ignores a failure.

## Limitations

- Linux x86_64 only. No Windows, macOS, or ARM packages at this time.
- Cosmya only audits; it never proposes or applies code changes.
- Audit quality depends entirely on the configured AI model and the
  project's size/complexity relative to the model's context window.
- Ollama support requires a locally running Ollama daemon with models
  already pulled (`ollama pull <model>`); Cosmya does not install Ollama
  itself.

## License

Cosmya is distributed under the
[YO-LE-ZZ COMMUNITY LICENSE v1.0](./LICENSE), copyright (c) yo-le-zz.

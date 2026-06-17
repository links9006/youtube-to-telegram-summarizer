# Contributing to all-youtube

Thanks for your interest in improving this project! This guide will help you get started.

## Code of Conduct

Be respectful and constructive. Harassment or abusive behaviour will not be tolerated.

## How Can I Contribute?

- 🐛 **Report bugs** — open an issue with a clear description, reproduction steps, and logs (redact any secrets!).
- 💡 **Suggest features** — open an issue describing the use case and proposed approach.
- 🔧 **Submit pull requests** — see the workflow below.
- 📣 **Share the project** — stars and mentions help others discover it.

## Development Setup

1. **Fork & clone** the repository.
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt   # linters / formatters
   ```
3. Copy `.env.example` → `.env` and fill in your **own** test credentials. Never use production keys.
4. Run the linters locally (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Pull Request Workflow

1. Create a branch off `main`:
   ```bash
   git checkout -b fix/short-description
   ```
2. Make your change. Keep commits focused — one logical change per commit, with a clear message.
3. Make sure your code passes the linters:
   ```bash
   ruff check app/
   ruff format --check app/
   ```
4. If you add a feature, update the README and, where relevant, `.env.example`.
5. Open a PR against `main` and fill in the PR template:
   - **What** does this change do?
   - **Why** is it needed?
   - **How** did you test it?

## Coding Standards

- **Python 3.10+**, type hints encouraged (`from __future__ import annotations` is already used).
- Keep functions small and single-purpose.
- Prefer the standard library where possible; justify every new dependency.
- No secrets in code — read everything from environment variables via [`app/config.py`](app/config.py).
- Add a short docstring to public functions/modules.

## Commit Message Style

Use the Conventional Commits format:

```
type(scope): short imperative summary

optional longer body
```

Examples: `fix(asr): reconnect Telethon on drop`, `feat(summary): retry delivery`, `docs: clarify env vars`.

## Reporting Security Issues

See [SECURITY.md](SECURITY.md) — do **not** open a public issue for security vulnerabilities.

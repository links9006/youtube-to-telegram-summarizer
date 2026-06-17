# Deploying all-youtube to GitHub

A step-by-step guide to publishing this project and keeping it clean.

## 0. What's already done (in this local copy)

- ✅ `.gitignore` excludes `.env`, `*.session`, `*.sqlite3`, `logs/`, `data/` runtime files, `__pycache__`, `.venv`, `diag_*.py`, `requeue_*.py`.
- ✅ Real `.env` is **not** tracked (verified).
- ✅ No API keys / tokens / session strings / production channel handles in any committed file (verified by scan).
- ✅ `.env.example`, LICENSE (MIT), CONTRIBUTING, SECURITY, README, CI workflow, issue/PR templates added.
- ✅ Initial commit exists: `git log --oneline` → `Initial public release`.

## 1. Create the repository on GitHub

1. Go to <https://github.com/new>.
2. **Repository name:** `all-youtube` (or your preferred name).
3. **Visibility:** **Public** (required — Codex for OSS only supports public repos).
4. **Do NOT** check "Add a README", "Add .gitignore", or "Choose a license" — we already have all of these locally. Initializing an empty repo avoids merge conflicts.
5. Click **Create repository**.

## 2. Push from this machine

GitHub no longer accepts password auth for git over HTTPS — you need one of:

### Option A — Personal Access Token (classic, simplest)

1. Create a token: <https://github.com/settings/tokens> → **Generate new token (classic)** → scope `repo` → copy it.
2. In this folder:

   ```bash
   git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/all-youtube.git
   git branch -M main
   git push -u origin main
   ```

3. When asked for a password, **paste the token** (username = your GitHub username).
   To avoid re-entering it, cache it:
   ```bash
   git config --global credential.helper store
   ```

### Option B — SSH (recommended long-term)

1. Generate a key if you don't have one: `ssh-keygen -t ed25519 -C "your_email@example.com"`.
2. Add the public key (`~/.ssh/id_ed25519.pub`) at <https://github.com/settings/keys>.
3. Then:
   ```bash
   git remote set-url origin git@github.com:<YOUR_GITHUB_USERNAME>/all-youtube.git
   git push -u origin main
   ```

## 3. Post-push checklist

- [ ] Open the repo on GitHub → confirm the README renders, the badge links work.
- [ ] Go to **Settings → Security → Code security** → enable **Secret scanning** and **Push protection** (free for public repos). This auto-blocks accidental token leaks in future commits.
- [ ] Go to **Actions** → confirm the `CI` workflow runs green on `main` (ruff lint + compile check).
- [ ] Add topics on the repo page (gear icon): `youtube`, `telegram-bot`, `whisper`, `openrouter`, `llm`, `summarization`, `python`, `self-hosted`.
- [ ] Add a short description and a project website/link (e.g. your channel) on the repo page.

## 4. KEEP SECRETS OUT — ongoing rules

- Never `git add .env`. It's ignored; keep it that way.
- Never commit `*.session`, `*.session-journal`, the SQLite DB, or `logs/`.
- If you ever add a new config key that's secret, put it only in `.env` (and document the **name** in `.env.example` with an empty value).
- If you ever leak a secret by mistake: **rotate it immediately** (it's compromised the moment it's pushed, even if you delete the commit after), then force-push the fix.

## 5. About the OpenAI "Codex for OSS" application — honest assessment

The program targets **maintainers of critical, widely-used open-source projects** ("criticality" — stars, monthly downloads, ecosystem importance). To maximize your chances realistically:

1. **Make it look maintained and real** before applying:
   - A clear, polished README (done).
   - License + contribution guide + security policy (done).
   - Green CI (done — will be green after first push).
   - At least a few commits showing real activity, ideally contributions from others later.
2. **Grow genuine usage signals**: stars, forks, issues from real users, references. Don't try to fake these — OpenAI reviews for authenticity, and fabricated activity can disqualify you and is against their terms.
3. **Be accurate in the form**: describe your real role (you're the sole maintainer right now — that's fine, say so), why the project matters (e.g. "an accessible, self-hostable alternative for turning video content into summaries, useful for accessibility, education, and content curation"), and how you'd use the API credits (e.g. "to improve summarization quality, add multi-language support, and run automated test coverage").
4. **Manage expectations**: a freshly published single-maintainer project is unlikely to be selected immediately — the program prioritizes projects with demonstrated impact. Treat the GitHub release as valuable for its own sake (portfolio, contributors, users) regardless of the OpenAI grant.

Set your GitHub username in the README badge URLs (search for `<OWNER>`) after you know the repo URL.

# Как разрешить ассистенту залить проект в твой GitHub

GitHub не принимает пароли для `git push` по HTTPS — нужен либо **Personal Access Token (PAT)**, либо **SSH-ключ**. Ниже два рабочих варианта. После любой из настроек ассистент сможет запушить проект за тебя.

---

## Вариант A (проще) — Personal Access Token

### 1. Создай репозиторий на GitHub
1. Открой <https://github.com/new>.
2. **Repository name:** `all-youtube`
3. **Visibility:** `Public` (обязательно публичный — нужно для Codex for OSS).
4. **НЕ** ставь галочки "Add README", ".gitignore", "license" — оставь пустым.
5. Нажми **Create repository**.

### 2. Создай токен
1. Открой <https://github.com/settings/tokens> (войдёшь под своим аккаунтом).
2. Нажми **Generate new token → Generate new token (classic)**.
3. Заполни:
   - **Note:** `all-youtube push` (любое описание)
   - **Expiration:** 7 дней (для разового пуша достаточно; можно дольше)
   - **Scopes:** поставь **только одну** галочку — `repo` (это включает весь подсписок repo).
4. Прокрути вниз → **Generate token**.
5. **Скопируй токен** (вида `ghp_xxxxxxxxxxxxxxxxxxxx`) — он показывается один раз.

### 3. Отдай токен и имя пользователя ассистенту
Напиши в чат:
- свой GitHub username
- токен (вставь как есть, `ghp_...`)

После этого ассистент выполнит:
```bash
git remote add origin https://<USERNAME>:<TOKEN>@github.com/<USERNAME>/all-youtube.git
git branch -M main
git push -u origin main
```
и проект окажется в репозитории.

> ⚠️ Токен = пароль от твоего GitHub. После заливки **удали его**: Settings → Tokens → Delete. Можешь сразу отозвать — push уже прошёл, он больше не нужен.

---

## Вариант B (без передачи токена) — SSH-ключ

Если не хочешь давать токен, можно сгенерировать SSH-ключ прямо здесь и добавить публичную часть на GitHub.

### 1. Ассистент генерирует ключ
```bash
ssh-keygen -t ed25519 -C "all-youtube-deploy" -f ~/.ssh/id_ed25519_github -N ""
cat ~/.ssh/id_ed25519_github.pub
```
Ассистент выдаст тебе строку ключа (начинается с `ssh-ed25519 AAAA...`).

### 2. Ты добавляешь ключ на GitHub
1. Открой <https://github.com/settings/ssh/new>.
2. **Title:** `all-youtube-deploy`
3. **Key:** вставь строку, которую дал ассистент.
4. **Add SSH key**.

### 3. Создай репозиторий (как в Варианте A, шаг 1) — публичный, пустой.

### 4. Отдай ассистенту username — он пушит по SSH
```bash
git remote add origin git@github.com:<USERNAME>/all-youtube.git
git -c core.sshCommand="ssh -i ~/.ssh/id_ed25519_github -o StrictHostKeyChecking=no" push -u origin main
```

---

## Вариант C (если установишь `gh` CLI) — ассистент создаст и зальёт репо сам

Если хочешь вообще без веб-интерфейса:
```bash
# установка gh (Ubuntu/Debian):
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh -y
gh auth login   # выбери GitHub.com → HTTPS → браузер или вставь токен
```
После `gh auth login` ассистент одной командой создаст репо и запушит:
```bash
gh repo create all-youtube --public --source=. --remote=origin --push
```

---

## После пуша — что проверить ассистенту/тебе
1. Открой `https://github.com/<USERNAME>/all-youtube` — README должен красиво отрисоваться.
2. Вкладка **Actions** — workflow `CI` должен позеленеть (ruff + compile check).
3. **Settings → Security → Code security** → включить **Secret scanning** и **Push protection** (защита от случайной утечки токенов в будущем).
4. На главной репо нажми шестерёнку справа → добавь **topics**: `youtube`, `telegram-bot`, `whisper`, `openrouter`, `summarization`, `python`.
5. Подставь свой username в badge-ссылки в `README.md` (искать `<OWNER>`).

---

## Рекомендация
**Вариант A** — самый быстрый (3 минуты). Токен можно сразу отозвать после пуша, так что риск минимальный. Если не хочешь передавать токен — **Вариант B (SSH)**, он вообще не требует раскрытия секрета.

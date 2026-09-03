# CodeVis &mdash; GitHub Push Guide

This walks you through publishing this project to your own GitHub account
from scratch, including handling the two things people most often get
wrong: accidentally committing secrets, and messy first commits.

---

## 1. One-time setup (skip if already done)

Check whether Git knows who you are:

```bash
git config --global user.name
git config --global user.email
```

If either is empty:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Make sure you're logged into GitHub in your browser, and decide how you'll
authenticate pushes (pick one):

- **GitHub CLI (easiest):** `gh auth login` (install from https://cli.github.com)
- **HTTPS + Personal Access Token:** GitHub → Settings → Developer settings →
  Personal access tokens → generate one with `repo` scope. You'll paste this
  token as your password the first time you push.
- **SSH key:** GitHub → Settings → SSH and GPG keys → add your public key
  (`cat ~/.ssh/id_ed25519.pub`). If you don't have a key yet:
  `ssh-keygen -t ed25519 -C "you@example.com"`.

---

## 2. Create the repository on GitHub

**Option A &mdash; GitHub CLI (fastest):**
```bash
cd codevis
gh repo create codevis --public --source=. --remote=origin
```
This creates the GitHub repo *and* wires up your local `origin` remote in
one command. Skip to step 4.

**Option B &mdash; GitHub website:**
1. Go to https://github.com/new
2. Repository name: `codevis`
3. Description: `Write Code. See Logic. Understand Flow. — an interactive code execution and flowchart visualization platform for Python, C, and C++.`
4. Visibility: **Public** (so it shows in your portfolio) or Private
5. **Do NOT** check "Add a README" / ".gitignore" / "license" &mdash; this
   project already has all three, and letting GitHub create its own would
   cause a merge conflict with your first push.
6. Click **Create repository**. Keep the page open &mdash; it shows the
   remote URL you'll need next.

---

## 3. Initialize Git locally and make the first commit

From the project root (the folder containing `README.md`, `backend/`, `frontend/`):

```bash
cd codevis
git init
git add .
git status
```

**Before committing**, look at the `git status` output and confirm you do
**not** see any of these:
- `.env` (only `.env.example` should be tracked)
- `__pycache__/` or `.venv/`
- any file containing an API key, password, or token

If you see any of those, the `.gitignore` shipped with this project should
already exclude them &mdash; if one still shows up, check you didn't rename
`.gitignore` by accident, then re-run `git status`.

Now commit:

```bash
git commit -m "Initial commit: CodeVis full-stack platform"
```

---

## 4. Connect to GitHub and push

If you used **Option A** above, your remote is already set &mdash; just run:

```bash
git branch -M main
git push -u origin main
```

If you used **Option B** (website), copy the URL GitHub showed you and run
**one** of these (whichever matches how you authenticate):

```bash
# HTTPS
git remote add origin https://github.com/<your-username>/codevis.git

# SSH
git remote add origin git@github.com:<your-username>/codevis.git
```

Then:

```bash
git branch -M main
git push -u origin main
```

If prompted for a password over HTTPS, paste your Personal Access Token
(not your GitHub account password &mdash; GitHub no longer accepts those for
Git operations).

---

## 5. Verify

Refresh your repository page on GitHub. You should see:
- `README.md` rendered on the repo homepage
- `backend/`, `frontend/`, `docs/` folders
- No `.env`, `.venv/`, or `__pycache__/` anywhere in the file tree

---

## 6. Making future changes

The normal day-to-day loop:

```bash
git add .
git commit -m "Describe what you changed"
git push
```

For anything non-trivial, prefer a branch + pull request even if you're the
only contributor &mdash; it's good practice and reads well to anyone
reviewing your portfolio:

```bash
git checkout -b feature/add-java-adapter
# ... make changes ...
git add .
git commit -m "Add Java language adapter"
git push -u origin feature/add-java-adapter
# then open a Pull Request on GitHub and merge into main
```

---

## 7. Polishing the repo for recruiters/portfolio viewers

Once pushed, a few free improvements:

1. **Repo description + topics** (gear icon next to "About" on the repo
   page): add topics like `python`, `flask`, `ast`, `compiler`,
   `flowchart`, `visualization`, `full-stack`.
2. **Pin the repo** on your GitHub profile (Profile → Customize your pins).
3. **About section link**: if you deploy the live app (see
   `DEPLOYMENT.md`), add the URL to the repo's "About" section.
4. **Social preview image**: Settings → General → Social preview &mdash; a
   screenshot of the workspace with a flowchart on screen works well.
5. Replace the placeholder GitHub link in `frontend/index.html` and
   `frontend/landing.html` (`href="https://github.com/"`) with your real
   repo URL.

---

## 8. Troubleshooting

| Error | Fix |
|---|---|
| `remote origin already exists` | You already ran `git remote add` once; use `git remote set-url origin <url>` instead |
| `Updates were rejected because the remote contains work that you do not have locally` | You checked "Add a README" when creating the repo despite the instructions above; run `git pull origin main --allow-unrelated-histories`, resolve any conflicts, then push again |
| `Support for password authentication was removed` | Use a Personal Access Token or SSH key, not your account password (see step 1) |
| `Permission denied (publickey)` | Your SSH key isn't added to the ssh-agent or GitHub; run `ssh-add ~/.ssh/id_ed25519` and confirm the key is listed under GitHub → Settings → SSH keys |
| Large/binary files rejected | This project shouldn't produce any &mdash; if you see this, check you didn't accidentally commit a compiled binary (`main`, `*.o`) that the `.gitignore` should have caught |

# CodeVis — Deployment Guide

This covers taking CodeVis from your local machine to a publicly reachable
deployment. Read the **"Which hosts actually work"** section before
picking a platform — this app's execution model (spawning `gcc`/`g++`/
`python3` subprocesses with OS-level resource limits) rules out several
popular "free" serverless options, and it's better to know that up front
than after a failed deploy.

---

## 1. Which hosts actually work

CodeVis's backend needs to:
- spawn subprocesses (`gcc`, `g++`, `python3`),
- call `resource.setrlimit()` and `os.setsid()`/`os.killpg()` (POSIX-only),
- write to a scratch temp directory,
- run for the lifetime of a request without an artificially short function timeout.

| Platform type | Works? | Notes |
|---|---|---|
| **VPS** (DigitalOcean, Linode, a home server, etc.) | ✅ Yes | Full control; simplest path. Run via `docker compose up` or gunicorn + systemd. |
| **Render / Railway / Fly.io** (Docker-based web services) | ✅ Yes | Free/hobby tiers support long-running containers with subprocess access. Use `backend/Dockerfile`. |
| **A container platform generally** (any host that runs an arbitrary Docker image as a long-lived service) | ✅ Yes | This is the architecture `backend/Dockerfile` targets. |
| **AWS Lambda / Google Cloud Functions / Vercel Serverless Functions** | ❌ No | These sandbox `fork()`/`setrlimit()` themselves and often lack `gcc`/`g++` in the runtime image; you'd be sandboxing inside someone else's sandbox with restrictions this project doesn't control. |
| **Cloudflare Workers** | ❌ No | V8-isolate runtime, no subprocess support at all. |
| **Static hosts (GitHub Pages, Netlify, Vercel *static*, Cloudflare Pages)** | ✅ For the **frontend only** | These serve `frontend/` perfectly (it's just static files) but cannot run the backend. |

**Recommended combo for a free/cheap public demo**: frontend on GitHub
Pages or Netlify (static, generous free tiers), backend on Render or
Fly.io's free/hobby container tier.

---

## 2. Deploying the frontend (static hosting)

The frontend is `frontend/` as-is — no build step.

### GitHub Pages
```bash
# from the repo root, after pushing to GitHub (see GITHUB_GUIDE.md)
git subtree push --prefix frontend origin gh-pages
```
Then enable Pages in your repo's Settings → Pages → source: `gh-pages`
branch. Your site will be at `https://<username>.github.io/codevis/`.

### Netlify / Vercel (drag-and-drop or CLI)
Point either platform's "static site" import at the `frontend/` folder as
the publish directory, with no build command. Both offer a CLI
(`netlify deploy`, `vercel`) if you prefer that to the web UI.

### Any other static host
Upload the contents of `frontend/` as-is. There is nothing to configure
beyond serving `index.html` and `landing.html`.

### ⚠️ One manual step every deployment needs

Before deploying, point the frontend at your backend's real URL. Open
`frontend/index.html` and edit this line near the top:

```html
<script>
  window.CODEVIS_API_BASE = window.CODEVIS_API_BASE || "http://localhost:5001";
</script>
```

Change `"http://localhost:5001"` to your deployed backend's URL (e.g.
`"https://codevis-backend.onrender.com"`). This is a one-line manual edit
by design — introducing a templating/build step to avoid it would
contradict the project's zero-build-step frontend architecture (see
`docs/TECHNICAL_DOCS.md`, "Frontend Architecture") for a change this
small.

---

## 3. Deploying the backend

### Option A: Render / Railway / Fly.io (Docker)

1. Push your repo to GitHub (see `GITHUB_GUIDE.md`).
2. Create a new **Web Service** (Render) / **Service** (Railway) /
   **App** (Fly.io) pointing at your repo.
3. Set the Docker build context to `backend/` and the Dockerfile path to
   `backend/Dockerfile` (Render and Railway both expose this as a field
   in their UI; Fly.io reads `fly.toml`, which you'd generate with
   `fly launch` from inside `backend/`).
4. Set environment variables from `.env.example` if you want non-default
   sandbox limits (none are required — sensible defaults are built in).
5. Deploy. Note the public URL you're given — you'll need it for step 2
   above (the frontend's `CODEVIS_API_BASE`).
6. **Update CORS for production.** `backend/app.py`'s
   `add_security_headers` currently sends
   `Access-Control-Allow-Origin: *`, which is fine for local development
   and a public demo, but for anything handling sensitive data you should
   restrict it to your actual frontend origin:

   ```python
   resp.headers["Access-Control-Allow-Origin"] = "https://your-frontend-domain.com"
   ```

### Option B: A VPS with Docker Compose

```bash
git clone https://github.com/<you>/codevis.git
cd codevis
cp .env.example .env      # adjust if desired
docker compose up --build -d
```

This runs both `frontend` (nginx, port 8080) and `backend` (gunicorn,
port 5001) as defined in `docker-compose.yml`. Put a reverse proxy
(nginx/Caddy) in front with TLS (Let's Encrypt via Certbot or Caddy's
automatic HTTPS) for a real public domain.

### Option C: A VPS without Docker

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-prod.txt
gunicorn --bind 0.0.0.0:5001 --workers 2 --threads 2 app:app
```
Run this under `systemd` or `supervisord` so it restarts on crash/reboot.

---

## 4. Hardening the execution sandbox further (optional, recommended for public multi-tenant use)

The sandbox described in `docs/TECHNICAL_DOCS.md` ("Security Model") is
real process-level isolation (CPU/memory/process-count/wall-clock limits,
guaranteed process-group cleanup) and is what this project runs and tests
against. If you're exposing CodeVis publicly to untrusted strangers at
scale, add a second, independent layer using
`backend/docker/Dockerfile.execution`:

1. Build the hardened execution image: `docker build -t codevis-executor -f backend/docker/Dockerfile.execution backend`
2. Run each execution inside that container (`--network none`, read-only
   root filesystem, non-root user, dropped capabilities — flags are
   documented in the Dockerfile itself) instead of directly on the
   backend host.
3. This requires modifying `execution/runners.py` to shell out to
   `docker run` (or, for lower latency, to a small persistent worker pool
   behind an internal RPC) instead of invoking `gcc`/`python3` directly.
   This wiring is intentionally left as a roadmap item — see
   `docs/TECHNICAL_DOCS.md`, "Future Improvements" — rather than shipped
   without being tested end-to-end.

---

## 5. Post-deployment checklist

- [ ] Frontend loads and Monaco Editor renders (needs outbound internet in the *visitor's* browser to reach the CDN — see `docs/TECHNICAL_DOCS.md`)
- [ ] `curl https://your-backend-url/api/health` returns `{"status":"ok",...}`
- [ ] Running a sample program end-to-end in the deployed workspace works
- [ ] CORS restricted to your real frontend origin (see step 3 above) if this isn't meant to be a fully open public API
- [ ] `.env` was never committed (check with `git log --all --full-history -- .env`)
- [ ] Sandbox limits (`CODEVIS_CPU_LIMIT`, `CODEVIS_MEM_LIMIT_MB`, etc.) reviewed for your expected traffic/abuse tolerance
- [ ] Update the README's "Live demo" line with your real URL

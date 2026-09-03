# =============================================================================
# CodeVis - backend application image
# =============================================================================
# This packages the Flask API itself (gunicorn-served) together with the
# compilers/interpreter it shells out to (gcc, g++, python3). It runs code
# through the same process-level sandbox as local development
# (execution/sandbox.py) -- see docs/TECHNICAL_DOCS.md "Security Model" for
# why that's an intentionally different concern from the per-execution
# hardened container in docker/Dockerfile.execution, and DEPLOYMENT.md for
# which hosts this image is (and isn't) appropriate for.
#
# NOTE ON VERIFICATION: this Dockerfile was written and carefully reviewed
# but not build-tested in the sandboxed environment this project was
# developed in (no Docker available there -- see docs/TECHNICAL_DOCS.md,
# "Development Process Notes"). The Python application code it packages
# (backend/app.py and everything it imports) *was* fully tested; only the
# container build itself was not. Please run `docker build` yourself before
# depending on this in production, and open an issue if it needs adjusting
# for your platform.
#
# Build:  docker build -t codevis-backend -f backend/Dockerfile backend
# Run:    docker run -p 5001:5001 --env-file .env codevis-backend
# =============================================================================

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

RUN useradd --no-create-home --shell /usr/sbin/nologin codevis \
    && chown -R codevis:codevis /app
USER codevis

ENV PORT=5001
EXPOSE 5001

# 2 workers x 2 threads is a reasonable default for a CPU/subprocess-bound
# workload like this one; tune via the WEB_CONCURRENCY env var per host.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-2} --threads 2 --timeout 30 app:app"]

# =============================================================================
# CodeVis - frontend static asset image
# =============================================================================
# The frontend has no build step (see docs/TECHNICAL_DOCS.md, "Frontend
# Architecture") so this image is just nginx serving the static files
# as-is. Not build-tested in this sandbox (no Docker available) -- see
# backend/Dockerfile's note; the files it copies were verified with
# `python3 -m http.server` instead (see SETUP_GUIDE.md).
#
# Build:  docker build -t codevis-frontend -f frontend/Dockerfile frontend
# Run:    docker run -p 8080:80 codevis-frontend
# =============================================================================

FROM nginx:1.27-alpine

COPY . /usr/share/nginx/html

EXPOSE 80

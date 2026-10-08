# BioMarkHER2 -- containerized review viewer.
#
# The same portal app/server.py serves: real accounts (app/auth.py), but
# plain HTTP. docker-compose.yml binds it to 127.0.0.1 on the host; to serve
# other machines, put an HTTPS reverse proxy in front and set
# BIOMARK_SECURE_COOKIES=1 -- see docs/ACCOUNTS_AND_ADMIN.md.
#
# Build & run (Docker only -- the React portal is built inside the image):
#   docker compose up --build
# Then open http://127.0.0.1:8000. On the first run `docker compose logs`
# shows the one-time link that creates the administrator account, or:
#   docker compose exec biomarkher2 python -m app.admin_cli create-admin --email ... --name ...
# Deployment guide: docs/DEPLOYMENT.md.

# ---- stage 1: build the React portal (Node only exists in this stage) ----
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ---- stage 2: the server ----
FROM python:3.11-slim

# libgomp1: PyTorch's CPU backend links against it; without it `import torch`
# fails at runtime inside the slim image, far from anything that looks like
# the cause.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before code: this layer only invalidates when requirements.txt
# changes, not on every source edit, which is most of a rebuild's time on a
# torch install.
#
# torch/torchvision are deliberately NOT in requirements.txt (see its own
# comment) -- plain PyPI serves a much larger GPU build by default, which is
# both wrong for this CPU-only project and hundreds of MB heavier than it
# needs to be. Installed here from PyTorch's own CPU wheel index instead,
# pinned to the exact versions this project was built and tested against.
# torchvision provides the ResNet18 encoder models/unet_seg.py imports
# (adopted in Phase 5) -- the image fails at import time without it.
RUN pip install --no-cache-dir torch==2.13.0 torchvision==0.28.0 \
    --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY models ./models
COPY preprocessing ./preprocessing
COPY training ./training
COPY evaluation ./evaluation
# wsi/: whole-slide reading, exclusions (ink, control cores) and the /api/slides routes.
# app/server.py imports it at start-up -- leaving it out made the container
# exit immediately with ModuleNotFoundError (found 2026-10-03).
COPY wsi ./wsi
COPY configs ./configs

# Only the built static portal from stage 1 -- no Node, no node_modules here.
COPY --from=ui /ui/dist ./ui/dist

# Not copied: data/ and artifacts/. Both are large (the patch dataset is
# ~1.5 GB; checkpoints are hundreds of MB) and machine-specific -- see
# .dockerignore. Mounted as volumes instead (docker-compose.yml), so a
# dataset or checkpoint never has to be baked into an image layer and
# re-uploaded on every code change.
# Run as an unprivileged user: a bug in request handling must not be able to
# write outside the mounted artifacts/ directory.
RUN mkdir -p /app/artifacts /app/data \
    && useradd --system --uid 10001 --home /app biomark \
    && chown -R biomark /app/artifacts
USER biomark

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# /api/health is public and reports only whether the models are loaded.
# Model loading takes ~30-60 s on CPU, hence the start period.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=8).status == 200 else 1)"

# Binds to 0.0.0.0 INSIDE the container -- Docker's own network isolation is
# what makes this safe; docker-compose.yml maps that to 127.0.0.1 only on the
# host. Publishing it more broadly needs HTTPS in front (a reverse proxy) and
# BIOMARK_SECURE_COOKIES=1; the accounts themselves are already enforced.
ENTRYPOINT ["python", "-m", "app.server", "--host", "0.0.0.0"]
# Models are read from the mounted artifacts/ (see docs/DEPLOYMENT.md for the
# exact files): the stain map (phase2_unet_8epochs, the adopted 8-epoch model)
# and the AI pre-score (v2/run_b). Whole slides are read from data/slides.
CMD ["--run", "artifacts/phase2_unet_8epochs", "--patch-root", "data/raw", \
     "--prescore-run", "artifacts/v2/run_b/best.pt", \
     "--slide-root", "data/slides"]

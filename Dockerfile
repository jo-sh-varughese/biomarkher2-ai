# BioMarkHER2 -- containerized review viewer.
#
# This packages the SAME local review viewer app/server.py already warns
# about: no authentication, no transport security, a pre-scoring aid meant to
# be demonstrated locally, not exposed to a network. Docker changes how it is
# launched, not what it is safe to expose it to -- see docker-compose.yml,
# which binds only to 127.0.0.1 on the host for exactly that reason.
#
# Build & run:
#   docker compose up --build
# Then open http://127.0.0.1:8000 -- same as running app/server.py directly.

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
# torch is deliberately NOT in requirements.txt (see its own comment) --
# plain PyPI serves a much larger GPU build by default, which is both wrong
# for this CPU-only project and hundreds of MB heavier than it needs to be.
# Installed here from PyTorch's own CPU wheel index instead, pinned to the
# exact version this project was built and tested against.
RUN pip install --no-cache-dir torch==2.13.0 \
    --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY models ./models
COPY preprocessing ./preprocessing
COPY training ./training
COPY evaluation ./evaluation
COPY configs ./configs

# Not copied: data/ and artifacts/. Both are large (the patch dataset is
# ~1.5 GB; checkpoints are hundreds of MB) and machine-specific -- see
# .dockerignore. Mounted as volumes instead (docker-compose.yml), so a
# dataset or checkpoint never has to be baked into an image layer and
# re-uploaded on every code change.
RUN mkdir -p /app/artifacts /app/data

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Binds to 0.0.0.0 INSIDE the container -- Docker's own network isolation is
# what makes this safe; docker-compose.yml maps that to 127.0.0.1 only on the
# host, preserving the "local demonstration only" guarantee app/server.py's
# module docstring states. Do not publish this port more broadly without
# adding real authentication in front of it first.
ENTRYPOINT ["python", "-m", "app.server", "--host", "0.0.0.0"]
CMD ["--run", "artifacts/phase2_unet", "--patch-root", "data/raw"]

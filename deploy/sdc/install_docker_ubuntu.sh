#!/usr/bin/env bash
# Install Docker Engine + the Compose v2 plugin on Ubuntu (20.04 / 22.04 / 24.04).
# Needs outbound HTTPS to download.docker.com (or archive.ubuntu.com for the fallback).
#   sudo bash install_docker_ubuntu.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
. /etc/os-release
echo "Ubuntu $VERSION_ID ($VERSION_CODENAME)"

apt-get update
apt-get install -y ca-certificates curl gnupg

if curl -fsS "https://download.docker.com/linux/ubuntu/dists/$VERSION_CODENAME/Release" >/dev/null; then
  echo "Using Docker's own repository."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  # Docker's repository may no longer carry this release (20.04 is past standard support).
  echo "Docker's repository has no $VERSION_CODENAME; using Ubuntu's docker.io + docker-compose-v2."
  apt-get install -y docker.io docker-compose-v2
fi

systemctl enable --now docker
docker --version
docker compose version

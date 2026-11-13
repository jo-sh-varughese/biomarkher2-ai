# BioMarkHER2: SDC deployment kit

Installs BioMarkHER2 on the State Data Centre VM (Ubuntu, Docker) behind HTTPS, with no internet needed after
Docker itself is installed. The full step-by-step guide is the handover's **Deployment Guide** (source:
`docs/handover/02_Deployment_Guide.md`).

| File | Run where | Purpose |
|---|---|---|
| `make_offline_bundle.sh` | Build machine (internet, Docker, repo with `artifacts/`) | Builds `dist/sdc_bundle/`: both images (`docker save`), the models, this folder, `SHA256SUMS` |
| `install_docker_ubuntu.sh` | VM, once, needs internet | Docker Engine + Compose v2 |
| `install.sh` | VM, from the copied bundle | Verifies, loads images, lays out `/opt/biomarkher2`, installs models, starts |
| `docker-compose.yml` | VM (`/opt/biomarkher2`) | `app` (portal, 127.0.0.1:8000) + `proxy` (Caddy, 443/80) |
| `Caddyfile` | VM | HTTPS with the SDC certificate or a self-signed one |
| `.env.example` | VM, copied to `.env` | Hostname, TLS, site name, scanner µm/px, validation record |
| `smoke_test.sh` | VM | Post-install / post-update checks |
| `backup.sh` | VM, nightly via cron | Consistent backup of all records (not models or slides) |

Quick path:

```bash
# build machine
bash deploy/sdc/make_offline_bundle.sh            # -> dist/sdc_bundle
scp -r dist/sdc_bundle admin@10.5.93.57:~

# VM
cd ~/sdc_bundle
sudo bash deploy/install_docker_ubuntu.sh          # once, with internet
sudo bash deploy/install.sh
sudo nano /opt/biomarkher2/.env && (cd /opt/biomarkher2 && sudo docker compose up -d)
sudo docker compose -f /opt/biomarkher2/docker-compose.yml exec app python -m app.admin_cli create-admin --email … --name "…"
sudo bash /opt/biomarkher2/smoke_test.sh
```

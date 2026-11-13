---
title: Deployment Guide
subtitle: Installing and operating BioMarkHER2 on the SDC VM
doc_id: BMH-SDC-02
---

# Deployment Guide

| | |
|---|---|
| Target | SDC VM `KDISC_KASP_DB` (10.5.93.57), 4 vCPU, 8 GB RAM, 100 GB disk, Ubuntu 20.04, x86-64 |
| Release | `sdc-2026.11.11` |
| Install folder | `/opt/biomarkher2` |
| Kit | `04_Deployment/sdc_bundle/` in this handover (images, models, `deploy/` scripts) |
| Effort | About half a day once VPN, SSH and sudo access work |

This guide installs the release, configures HTTPS, creates the first administrator, sets up backups and verifies
the result. Before handover, `install.sh`, `smoke_test.sh`, `backup.sh` and the restore procedure were run end to end
from this exact bundle on a clean Linux Docker host. Commands beginning `$` are run
as the admin user on the VM; `sudo` is shown where needed.

## 1. What gets installed

| Component | Form | Listens on |
|---|---|---|
| `app`: portal, API, models, PDF reports | Docker image `biomarkher2:sdc-2026.11.11` (2.1 GB loaded; `images.tar.gz` is 0.5 GB) | `127.0.0.1:8000` only |
| `proxy`: HTTPS termination | Docker image `caddy:2-alpine` | `0.0.0.0:443`, `0.0.0.0:80` (redirect) |
| Model files | `biomark_models.tgz` (≈185 MB), checksum-verified | read from `/opt/biomarkher2/artifacts` |
| Records | SQLite databases and JSONL logs | `/opt/biomarkher2/artifacts` |
| Slides | Whole-slide image files | `/opt/biomarkher2/slides` |

Layout after installation:

```
/opt/biomarkher2/
├── docker-compose.yml     two services: app, proxy
├── Caddyfile              HTTPS settings
├── .env                   site settings (hostname, TLS, site name, scanner µm/px)
├── artifacts/             models + all records  (owner uid 10001, mode 700)  ← back up
├── slides/                whole-slide files     (owner uid 10001)
├── certs/                 SDC certificate and key (cert.pem, key.pem)
├── backups/               nightly archives
└── install.sh  backup.sh  smoke_test.sh  install_docker_ubuntu.sh
```

## 2. Prerequisites from SDC

| # | Item | Status / note |
|---|---|---|
| 1 | VPN account and SSH (22) access to 10.5.93.57 with sudo | VPN credentials issued; to be tested |
| 2 | Inbound 443 and 80 from the VPN/user network to the VM | Required |
| 3 | Temporary outbound HTTPS for Docker installation | Internet enabled until **15-11-2026 EOD** |
| 4 | Internal DNS name and TLS certificate for the portal | Requested; until then the VM IP with a self-signed certificate works |
| 5 | Confirmation that Docker may be installed and the VM is dedicated | Requested |
| 6 | Firewall / VPN upload limits | Slides are 0.3–0.7 GB; uploads are allowed up to 8 GB. If the VPN cuts large uploads, copy slides by SFTP (§7.3) |

> **Do the internet-dependent step (§3, Docker) before 15-11-2026.** Everything after §3 works with no internet:
> the application images and models are copied in as files.

## 3. Install Docker (needs internet once)

Connect over VPN, then:

```bash
$ ssh <admin-user>@10.5.93.57
$ scp -r sdc_bundle <admin-user>@10.5.93.57:~        # from your workstation, if not already copied
$ cd ~/sdc_bundle
$ sudo bash deploy/install_docker_ubuntu.sh
```

The script uses Docker's own repository, or Ubuntu's `docker.io` + `docker-compose-v2` packages if Docker's repository
no longer carries Ubuntu 20.04. Expected end of output:

```
Docker version 2x.x.x, build …
Docker Compose version v2.x.x
```

If the VM is upgraded to Ubuntu 22.04 or 24.04 (recommended: 20.04 is past standard support), run this step after
the upgrade.

## 4. Install BioMarkHER2

```bash
$ cd ~/sdc_bundle
$ sha256sum -c SHA256SUMS                  # every line must say OK
$ sudo bash deploy/install.sh
```

`install.sh` verifies the bundle, loads both images (`docker load`), creates `/opt/biomarkher2`, extracts and
verifies the models (`sha256sum -c artifacts/MODELS.sha256`), sets ownership to uid 10001 (the unprivileged user the
container runs as), starts both containers and waits for the health check:

```
{"status": "ok", "stain_model": true, "prescore_model": true, "slides": true}
```

Model loading takes 30–60 seconds. Re-running `install.sh` is safe: it keeps `.env`, accounts, reviews and slides.

### 4.1 When the VPN is too slow to copy the images (as at the SDC, November 2026)

The SDC VPN carried about 0.1 MB/s, so `images.tar.gz` (0.5 GB) would take over an hour. While the VM still has
internet access, build the image on the VM instead and copy only the source and the models:

```bash
# from the workstation (12 MB, then 185 MB)
$ scp biomarkher2-sdc-2026.11.11-source.zip biomark_models.tgz root@10.5.93.57:/root/
# on the VM
$ apt-get install -y unzip && unzip -q biomarkher2-sdc-2026.11.11-source.zip -d /root/src
$ cd /root/src/biomarkher2-sdc-2026.11.11
$ docker pull caddy:2-alpine && docker build -t biomarkher2:sdc-2026.11.11 .     # about 3 minutes
$ mkdir -p /opt/biomarkher2/{artifacts,slides,certs,backups}
$ cp deploy/sdc/docker-compose.yml deploy/sdc/Caddyfile deploy/sdc/*.sh /opt/biomarkher2/
$ cp deploy/sdc/.env.example /opt/biomarkher2/.env
$ tar -xzf /root/biomark_models.tgz -C /opt/biomarkher2
$ cd /opt/biomarkher2 && sha256sum -c artifacts/MODELS.sha256 && chown -R 10001 artifacts slides
$ docker compose up -d && bash smoke_test.sh
```

The Dockerfile pins every dependency version, so the result is the same image as the bundle's. This is how the
release was installed at the SDC on 13 November 2026.

## 5. Configure the site

Edit `/opt/biomarkher2/.env`:

```bash
$ sudo nano /opt/biomarkher2/.env
```

| Setting | Value at SDC | Meaning |
|---|---|---|
| `BIOMARK_HOSTNAME` | `10.5.93.57`, later the SDC DNS name | What users type in the browser |
| `BIOMARK_TLS` | `internal` until SDC issues a certificate; then `/certs/cert.pem /certs/key.pem` | HTTPS certificate |
| `BIOMARK_SITE_NAME` | `Government Medical College Kottayam` (or as agreed with K-DISC) | Printed on every result and report; the safety gate uses it |
| `BIOMARK_SITE_MPP` | `0.286` | Scanner microns per pixel (Medprime scans received from K-DISC). Confirm for the scanner actually used |
| `BIOMARK_SITE_VALIDATION` | *(empty)* | Empty = AI pre-score withheld (shadow mode) until local validation (§10) |
| `BIOMARK_ANALYSIS_SLOTS` | `1` | Analyses at once; others queue. Use `2` with 8 vCPU / 16 GB |

Apply changes:

```bash
$ cd /opt/biomarkher2 && sudo docker compose up -d
```

### 5.1 Installing the SDC certificate

Copy the certificate (full chain, PEM) and private key, then switch `.env`:

```bash
$ sudo cp her2.crt /opt/biomarkher2/certs/cert.pem
$ sudo cp her2.key /opt/biomarkher2/certs/key.pem
$ sudo chmod 644 /opt/biomarkher2/certs/cert.pem && sudo chmod 640 /opt/biomarkher2/certs/key.pem
$ sudo sed -i 's#^BIOMARK_TLS=.*#BIOMARK_TLS=/certs/cert.pem /certs/key.pem#' /opt/biomarkher2/.env
$ sudo sed -i 's#^BIOMARK_HOSTNAME=.*#BIOMARK_HOSTNAME=<dns-name-on-the-certificate>#' /opt/biomarkher2/.env
$ cd /opt/biomarkher2 && sudo docker compose up -d --force-recreate proxy
```

With `BIOMARK_TLS=internal`, Caddy makes its own certificate. Browsers then show a warning the first time; that is
acceptable for the pilot but not for routine use.

## 6. Create the first administrator

Either from the shell (recommended; the password is typed at a hidden prompt):

```bash
$ cd /opt/biomarkher2
$ sudo docker compose exec app python -m app.admin_cli create-admin --email <email> --name "<full name>"
```

or open the one-time setup link printed at start-up. Replace its `http://127.0.0.1:8000` part with
`https://<BIOMARK_HOSTNAME>`:

```bash
$ sudo docker compose logs app | grep 'setup?token='
```

The link works once and only until the container restarts. Then sign in at `https://<BIOMARK_HOSTNAME>` and add
users from **Admin console → Users** (Administrator Manual §3). Create **two** administrators so a forgotten
password cannot lock everyone out.

## 7. Verify

### 7.1 Smoke test

```bash
$ sudo bash /opt/biomarkher2/smoke_test.sh
BioMarkHER2 smoke test (10.5.93.57)
  OK    containers running
  OK    app healthy (docker healthcheck)
  OK    both models loaded
  OK    model checksums
  OK    HTTPS answers
  OK    HTTP redirects to HTTPS
  OK    secure-cookie mode on (HSTS sent)
  OK    port 8000 not exposed beyond VM
  OK    slides folder writable by the app
  OK    disk below 80%
Site gate: SHADOW_MODE (pre-scores withheld)
```

### 7.2 From a VPN client

1. Open `https://<BIOMARK_HOSTNAME>`, sign in as the administrator.
2. **Admin console → System → Deployment readiness** should show 5/5 once there are two administrators.
3. **Field analysis**: upload any HER2 IHC field image (PNG/JPEG, 40×). Expect a result within about 30 seconds
   with cell evidence, ISH guidance, and "AI pre-score withheld at this site" (shadow mode).
4. **Whole slides → Upload slide**: upload one K-DISC slide; open it; **Analyse slide** (4–11 minutes).

### 7.3 Copying slides without the browser

Large slides can be copied over SFTP straight into the slides folder; they appear in the list at once:

```bash
$ scp slide.svs <admin-user>@10.5.93.57:/tmp/ && ssh <admin-user>@10.5.93.57 \
    'sudo mv /tmp/slide.svs /opt/biomarkher2/slides/ && sudo chown 10001 /opt/biomarkher2/slides/slide.svs'
```

## 8. Backups

Everything the system records is in `artifacts/`: accounts and the audit log (`biomark.db`), the case database
(`cases.sqlite3`), pathologist reviews (`reviews.jsonl`), region annotations (`annotations.jsonl`), the shadow
log (`prescore_shadow_log.jsonl`) and the learning store (`learning/`).

```bash
$ sudo bash /opt/biomarkher2/backup.sh          # manual run
$ echo '30 1 * * * root /opt/biomarkher2/backup.sh >> /var/log/biomark-backup.log 2>&1' | sudo tee /etc/cron.d/biomarkher2-backup
```

`backup.sh` takes consistent SQLite copies while the system is running, archives everything except the model files
and slides into `backups/biomark_<date>.tgz`, and keeps 14 days. **Copy `backups/` off the VM** (SDC backup system or
snapshot); a backup on the same disk does not survive a disk failure. Slides follow SDC's own retention policy.

**Restore** (test once before go-live):

```bash
$ cd /opt/biomarkher2 && sudo docker compose down
$ sudo mkdir -p /tmp/restore && sudo tar -xzf backups/biomark_<date>.tgz -C /tmp/restore
$ sudo cp -a /tmp/restore/artifacts/. artifacts/ && sudo cp /tmp/restore/db_snapshot/* artifacts/
$ sudo chown -R 10001 artifacts && sudo docker compose up -d
```

## 9. Day-to-day operation

| Task | Command (in `/opt/biomarkher2`) |
|---|---|
| Status | `sudo docker compose ps` |
| Logs | `sudo docker compose logs --tail 200 app` (or `proxy`) |
| Restart | `sudo docker compose restart` |
| Stop / start | `sudo docker compose down` / `sudo docker compose up -d` |
| Health | `curl -s http://127.0.0.1:8000/api/health` |
| Disk | `df -h /opt/biomarkher2 && sudo du -sh slides artifacts` |
| Reset a password | `sudo docker compose exec app python -m app.admin_cli reset-password --email <email>` |
| Unlock an account | `sudo docker compose exec app python -m app.admin_cli unlock --email <email>` |
| List users | `sudo docker compose exec app python -m app.admin_cli list-users` |

Containers restart automatically after a crash or a VM reboot (`restart: unless-stopped`). Logs rotate at
5 × 20 MB per container.

## 10. Site validation (turning the AI pre-score on)

The AI pre-score is withheld at this site until it is shown to work here (Technical Documentation §6.2, §8.1).

1. Run in shadow mode. Pathologists analyse cases and sign their own scores in **Pathologist review**. Aim for
   at least 100 cases covering 0, 1+, 2+ and 3+.
2. Export the shadow log and reviews (**Admin console → System → Exports**, plus
   `artifacts/prescore_shadow_log.jsonl`) and compare them with `scripts/evaluate_cap_agreement.py` on a
   workstation with the source code.
3. If the gate thresholds are met (≥ 100 cases, ≥ 90% accuracy, QWK ≥ 0.85, ≤ 1% off by two grades), write a validation
   record like `configs/site_validation/her2_ihc_40x.json` naming this site, copy it to
   `artifacts/site_validation.json`, set `BIOMARK_SITE_VALIDATION=artifacts/site_validation.json` in `.env`, and run
   `sudo docker compose up -d`. The log line `gate: VALIDATED` confirms it.
4. If they are not met, the pre-score stays withheld. Everything else remains in use.

## 11. Updating

### 11.1 Application update (new image)

On a build machine with internet: `bash deploy/sdc/make_offline_bundle.sh <new-tag>`. Copy the new `images.tar.gz`
to the VM, then:

```bash
$ sudo bash /opt/biomarkher2/backup.sh
$ gunzip -c images.tar.gz | sudo docker load
$ sudo sed -i 's#^BIOMARK_IMAGE_TAG=.*#BIOMARK_IMAGE_TAG=<new-tag>#' /opt/biomarkher2/.env
$ cd /opt/biomarkher2 && sudo docker compose up -d && sudo bash smoke_test.sh
```

Rollback: set the previous tag in `.env` and `docker compose up -d` (old images stay loaded until removed).

### 11.2 Model update

Replace files under `artifacts/` from a new `biomark_models.tgz`, check `sha256sum -c artifacts/MODELS.sha256`, then
`sudo docker compose restart app`. A new pre-score model invalidates its prediction-set calibration and any site
validation record; repeat §10. A new stain-map model needs `scripts/calibrate_conformal.py` re-run (the portal shows
"stale calibration" until then).

### 11.3 Locally learned versions

Administrators can train and activate a new pre-score head from signed local cases (Administrator Manual §8). This
needs no file transfer; versions and rollback live in `artifacts/learning/`.

## 12. Security summary

* Only 443 and 80 (redirect) are published; 8000 is bound to localhost. SSH (22) should be limited to the VPN.
* The application container runs as an unprivileged user (uid 10001) with no write access outside `artifacts/` and
  `slides/`.
* HTTPS with `Secure`, `HttpOnly`, `SameSite=Strict` session cookies, HSTS, CSRF tokens, security headers.
* Passwords hashed with scrypt; lockout after 5 failures; every sign-in, account change and export audited.
* No outbound connection at run time; no patient data leaves the VM except through audited exports.
* Store only pseudonymised patient references in the review form (no names).
* Close the temporary internet access after installation (SDC step 9 in the feasibility report).

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `app` keeps restarting | Model files missing or unreadable | `docker compose logs app`; check `sha256sum -c artifacts/MODELS.sha256`; `sudo chown -R 10001 artifacts` |
| `PermissionError` on `artifacts/` or `data/slides` | Ownership | `sudo chown -R 10001 /opt/biomarkher2/artifacts /opt/biomarkher2/slides` |
| Browser: "connection refused" | proxy not running or 443 blocked | `docker compose ps`; check SDC firewall for 443 from the VPN |
| Browser certificate warning | `BIOMARK_TLS=internal` | Install the SDC certificate (§5.1) |
| Sign-in works, then immediately signed out | Site opened over plain HTTP | Always use `https://` (secure cookies) |
| Slide upload fails part-way | VPN/firewall size or time limit | Raise the limit for this host, or copy by SFTP (§7.3) |
| Slide shows "no pre-score, magnification" | Slide coarser than 0.5 µm/px (below 20×) | Rescan at 20× or 40× |
| Field "Not assessable" | Quality gate (focus, stain, cells) | Read the reasons on screen; choose a better field |
| "AI pre-score withheld at this site" | Shadow mode, by design | §10 |
| Learning: "Reference features not found" | Reference file not shipped in this release | Technical Documentation §8.3 |
| Analyses slow or queued | 4 vCPU, one analysis at a time | Expected; request 8 vCPU / 16 GB for heavier use |
| Disk filling | Slides accumulate | Archive or delete old slides per retention policy |

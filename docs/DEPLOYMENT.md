# Deploying BioMarkHER2

One Docker container serves the whole system: the review portal (React,
built inside the image), the API, the three models and the PDF reports.
Patient images and every record stay on the server it runs on; nothing is
sent to any outside service.

## 1. What the server needs

| | Minimum | Comfortable |
|---|---|---|
| CPU | 4 cores (x86-64) | 8 cores |
| RAM | 8 GB | 16 GB (whole slides) |
| Disk | 5 GB + slides | SSD |
| Software | Docker 24+ with Compose v2 | |
| GPU | not needed | |

Speed on 4 CPU cores: a field about 20-30 s; a whole slide about 10-15 min
(tumour detection dominates).

## 2. Files the image does not contain

Models are mounted, not baked in, so a model update never needs a rebuild.
Copy them from the machine that has them:

```bash
bash scripts/package_models.sh        # -> dist/biomark_models.tgz (~305 MB)
# on the server, inside the cloned repo:
tar -xzf biomark_models.tgz
sha256sum -c artifacts/MODELS.sha256  # every line must say OK
```

| File | What it is |
|---|---|
| `artifacts/phase2_unet/best.pt` (+ `conformal_calibration.npz`, `conformal_calibration_ids.json`) | stain map and its pixel-level conformal calibration |
| `artifacts/v2/run_b/best.pt` (+ `prescore_sets.json`) | AI pre-score (ResNet-50 multi-task U-Net) and its conformal prediction-set calibration |
| `artifacts/tumour/best.pt` | invasive-tumour segmenter (whole slides) |

Whole-slide files (`.svs`, `.ndpi`, `.tiff`, `.mrxs`, ...) go in `data/slides/`.
`data/raw/` (example patches for the Field analysis picker) is optional.

## 3. Start it

```bash
git clone <repo> && cd biomarkher2-ai
# models: section 2
sudo chown -R 10001 artifacts        # Linux only: the container runs as uid 10001
BIOMARK_SITE_NAME="Government Medical College Kottayam" docker compose up -d --build
docker compose logs -f               # wait for "BioMarkHER2 portal -> http://..."
```

The first start prints a **one-time setup link** in the logs: open it to
create the first administrator. Then add users in Admin console -> Users
(docs/ACCOUNTS_AND_ADMIN.md). Or from the shell:

```bash
docker compose exec biomarkher2 python -m app.admin_cli create-admin --email you@hospital.org --name "Dr. ..."
```

Health: `curl http://127.0.0.1:8000/api/health` returns
`{"status": "ok", "stain_model": true, "prescore_model": true, "slides": true}`.
Docker also checks it every 30 s (`docker ps` shows `healthy`).

## 4. Site validation: the AI pre-score is withheld until you validate

The pre-score was validated on its training site only (holdout 92.3%,
QWK 0.975; at an unseen hospital accuracy fell as low as 48%). So at any other
site the server starts in **shadow mode**: the pre-score is computed and
logged (`artifacts/prescore_shadow_log.jsonl`) but not shown; cell evidence,
ISH decision support and everything else work normally.

To validate locally:

1. Run the portal in shadow mode while pathologists record their own scores
   in the Pathologist review tab (aim for 100+ cases covering 0/1+/2+/3+).
2. Compare the shadow log with the reviews (`scripts/evaluate_cap_agreement.py`)
   and write a validation record like `configs/site_validation/her2_ihc_40x.json`
   with this site's name, case count, accuracy, QWK and scanner microns-per-pixel.
3. Start with `--site-validation configs/site_validation/<site>.json`.
   The record counts only for the site it names, and the gate decides
   (`evaluation/safety_gate.py`).

`--research-prescores` shows unvalidated pre-scores marked "RESEARCH MODE,
not for patient care". Never use it for clinical work.

## 5. Making it reachable from other computers (HTTPS)

`docker-compose.yml` publishes the portal on `127.0.0.1:8000` only. To serve
the hospital network, put an HTTPS reverse proxy in front. For example,
Caddy:

```
her2.hospital.local {
    reverse_proxy 127.0.0.1:8000
}
```

Then enable in `docker-compose.yml` under `environment`:
`BIOMARK_SECURE_COOKIES: "1"` (Secure cookie + HSTS) and
`BIOMARK_TRUST_PROXY: "1"` (the audit log records the real client address).
Never publish the plain-HTTP port beyond the server itself.

## 6. Backups

Everything that matters is in `artifacts/`:

| File | Contents |
|---|---|
| `biomark.db` | accounts, sessions, settings, audit log |
| `reviews.jsonl` | every pathologist review (append-only) |
| `annotations.jsonl` | region annotations |
| `prescore_shadow_log.jsonl` | withheld pre-scores (for local validation) |

Back up `artifacts/` daily. Restoring is copying it back and starting the container.

## 7. Updating

```bash
git pull && docker compose up -d --build    # code
# models: replace the files, verify checksums, then
docker compose restart
```

A stain-map model change invalidates its conformal calibration; the portal
flags this ("stale calibration") until `scripts/calibrate_conformal.py` is re-run.

## 8. Before going live: checklist

- [ ] `sha256sum -c artifacts/MODELS.sha256` all OK
- [ ] `docker ps` shows the container `healthy`
- [ ] the administrator account exists and the setup link is used up
- [ ] `BIOMARK_SITE_NAME` is this hospital's name (the gate says "shadow mode")
- [ ] HTTPS proxy in place, both `BIOMARK_*` security settings on
- [ ] `artifacts/` backed up nightly, and a restore tested once
- [ ] slide scanner microns-per-pixel known (slides below 20x get no pre-score)
- [ ] pathologists briefed: every result is a suggestion; they sign the score

CI (`.github/workflows/tests.yml`) builds this image from a clean checkout on
every push and checks that the server and all its dependencies load inside it.

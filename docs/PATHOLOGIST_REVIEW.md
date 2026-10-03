# Pathologist review (laboratory record)

Status: built 2026-10-03, not committed. UI `ui/src/pages/Review.jsx` (sidebar
**Pathologist review**), record `app/review_record.py`, route `POST /api/review`.

## How it is reached
Field analysis and Whole slides each end with a **bottom action bar** (AI
pre-score, cell evidence and ISH suggestion at a glance, PDF report, **Open
pathologist review**). The sign-off form that used to sit in the Field
analysis rail moved here.

## What is recorded
One record per save, appended to the review log (never edited):

| Section | Fields |
|---|---|
| Specimen and pre-analytics | accession, pseudonymised patient reference, block, specimen type, antibody clone, fixation 6–72 h, cold ischaemia ≤ 1 h |
| Controls and adequacy | on-slide/run control, tissue adequacy, invasive cells assessed |
| HER2 IHC assessment | score 0/1+/2+/3+/cannot assess, HER2-ultralow flag, reporting category (ASCO/CAP 2023, derived), % complete-intense / complete-weak-moderate / incomplete-faint / none, heterogeneity, staining pattern, artefacts/excluded areas |
| Agreement with the AI | with the AI pre-score and with the cell evidence; a reason is required to disagree (it is how the model is audited) |
| Decision and follow-up | ISH (not required / ordered / recommended / available / deferred), second opinion |
| Comments | report comment, internal note |
| Snapshot | what the system showed: AI pre-score + confidence, gate status, cell category and count, ISH suggestion |
| Who / when | reviewer name, email, registration, review start time, save time |

## Rules enforced by the server
* Status **draft → preliminary → final**. A later save continues a draft or
  preliminary record as the next version.
* A **final** report needs the attestation box ("I have personally reviewed
  this case…") and is never changed; a change is an **amendment** with a
  stated reason, recorded as a new version that points at the old one.
* No final score on tissue marked inadequate (record "cannot assess").
* Cell percentages must not add up to more than 100%.
* The score is **not pre-filled from the AI**, to avoid automation bias.

## Also changed on 2026-10-03
* The stain-area "Key result" (which showed e.g. "1+" beside an AI "3+") is
  now "Stained area by intensity" with words (Negative/Weak/Moderate/Strong),
  folded under supporting measurements.
* The image **Enlarge** view is a real zoom/pan viewer (OpenSeadragon),
  centred and full-screen; it was pinned top-left and clipped at high browser
  zoom.
* Layout stacks earlier (≤ 1360 px CSS width), so 110–150% browser zoom no
  longer squeezes the results card; every page audited at 100/125/150/200%.
* The sidebar names both models (pre-score and stain map).

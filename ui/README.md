# BioMarkHER2 — review portal (React)

The pre-scoring review UI, rebuilt as a React application. It talks to the same
Python backend as before (`/api/context`, `/api/analyze`, `/api/review`,
`/api/report`) and falls back to built-in demo data when that backend is not
running, so the portal is always demonstrable.

## Run it

```bash
npm install
npm run dev       # http://localhost:5173/static/
```

The dev server binds all interfaces (`vite --host`), so a phone on the same
Wi-Fi can open the Network URL it prints — `http://<your-ip>:5173/static/`.

`npm run dev` proxies `/api/*` to `http://127.0.0.1:8000` (the Python
backend's default `--port`). Change the target in `vite.config.js` if the
backend listens elsewhere. With no backend up, every screen still works on
demo data and says so — a "Demo data" badge in the header strip and in the
sidebar's status block.

## Build and serve from the Python app

```bash
npm run build          # -> dist/, assets under /static/  (the Python backend)
npm run build:netlify  # -> dist/, assets under /          (Netlify)
```

`base` is `/static/`, so the built page loads its assets from
`/static/assets/…`. The backend is `app/server.py` (standard-library
`http.server` — no Flask/FastAPI; see its module docstring for why). It
already points at `dist/` by default (`--ui-dist`, defaulting to
`ui/dist`) and serves `dist/index.html` for every path that is not `/api/*`
or `/static/*` — the client-side-routing catch-all this portal needs, since
a hard refresh on `/analysis` or `/cases` must still return `index.html`.

The simplest way to run both build and server together is the **`biomark`**
command (see the repo root's README) — it builds `ui/dist` only when it is
missing or stale, then starts `app/server.py` pointed at it, so day-to-day
this whole section reduces to one command from the repo root:

```bash
biomark
```

## Landing page

Built with Tailwind + TypeScript on top of the existing JS portal. Three
integration notes, each of which caused a real bug first:

- **Tailwind preflight is disabled** (`tailwind.config.js`). It is a global
  reset and would restyle every screen of the portal, which has its own
  stylesheet. The resets the utilities genuinely need are scoped in
  `src/styles/halo.css`.
- **Those scoped resets are written `:where(.halo) a`, not `.halo a`.** A
  reset must never outrank the utilities it supports: `.halo a` scores (0,1,1)
  and beats `.text-white` at (0,1,0), which paints black text on the black
  pill buttons. Tailwind's `@layer base` does not fix this — it reorders
  output at build time but is not a native CSS cascade layer, so specificity
  still decides.
- **`background-image` data URIs are quoted.** The field images are SVG data
  URIs containing `rotate(...)`; `encodeURIComponent` leaves parentheses
  alone, so an unquoted `url()` terminates at the first one.

**TT Norms Pro is licensed and is not shipped here.** The `@font-face` rules
are wired for `/fonts/tt-norms-pro-{regular,semibold}.woff2` — drop those two
files into `public/fonts/` and they are picked up automatically. Until then
the stack falls through to Inter. The two 404s in the console are that, and
are harmless.

The landing chunk is ~188 kB gzipped, almost all of it three.js, and is
`React.lazy`-loaded so none of it is on the critical path for someone who
signs in and goes straight to a case.

### Motion

The public marketing page is at `/`; the portal sits under `/overview`,
`/analysis`, `/cases`, `/model`, `/method`.

Its hero is a 3D point cloud written by hand against a 2D canvas
(`src/components/landing/PointCloud.jsx`) rather than pulled from three.js:
the scene is a few thousand coloured points with perspective and depth
sorting, which is ~150 lines of maths against ~600KB of library on a page
whose whole job is to load fast. Each point is a tissue pixel carrying one of
the four HER2 classes in the portal's own palette, and scrolling morphs them
from a biopsy-shaped volume into an ordered plane — raw tissue becoming a
classified field. It pauses when off-screen, caps DPR at 2, and halves its
point count on narrow screens.

The layer stack renders the real output of the demo field generator the
portal itself uses, so the page illustrates what the product actually
produces rather than a mock-up that can drift away from it.

The positioning is deliberate. The headline leads with what the tool
*refuses* to do, and there is a full section on its limits above the final
call to action — both the honest framing and the stronger one, since it is
the only claim on the page a competitor cannot copy.

## Deployed

Live on Netlify: <https://biomarkher2-portal.netlify.app>

```bash
npm run deploy    # build:netlify, then netlify deploy --prod
```

There is no Python backend behind the Netlify build, so every screen runs on
demo data and labels itself as such. Deep links work because `netlify.toml`
rewrites every path to `index.html`; without that rule a shared link to
`/cases` would 404, since no such file exists on disk.

### The site is password protected

The whole site sits behind HTTP Basic Auth, enforced by the edge function in
`netlify/edge-functions/gate.ts` before any response is produced. An
unauthenticated visitor gets a 401 and receives no HTML, no JavaScript and no
demo data — not even the asset bundle.

This is the real gate. The sign-in screen *inside* the app is a demo login
that runs in the browser and protects nothing; it stays because it is part of
the portal's workflow, not because it secures anything.

Netlify's own password protection is a paid-plan feature, so this is the
free-tier equivalent. The credentials live in environment variables, never in
a committed file:

```bash
netlify env:set SITE_PASSWORD "new-password"   # then redeploy
netlify env:set SITE_USERNAME "gmck"
npm run deploy
```

If `SITE_PASSWORD` is unset the function fails closed and returns 503. Serving
the site wide open while appearing protected would be the worse failure — it
looks identical to success.

The two targets need different asset bases, which is why there are two build
scripts — selected by Vite mode rather than an environment variable, because
`VITE_BASE=/ vite build` looks portable but Git Bash on Windows rewrites the
lone `/` into a filesystem path and the build silently emits assets under
`/Program Files/Git/`.

## Languages

English and Malayalam, switchable from the toggle in the top bar — and on the
login screen, since a Malayalam reader meets that page first. The choice is
remembered and applied before the first paint, so the correct font is
requested immediately rather than after a reflow.

Strings live in `src/i18n/strings.js`, one tree per language, looked up with
`t("some.key")`. A missing Malayalam string falls back to English rather than
rendering a raw key — a gap should degrade to a readable word, not to
`analysis.rail.heading` in the middle of a clinical screen.

Four conventions, documented at the top of that file:

- **Technical terms stay in Latin script** — HER2, IHC, DAB, UNET, α, PDF.
  These are read as-is in Kerala pathology practice; transliterating them
  would make them harder to recognise, not easier.
- **Clinical vocabulary is transliterated into Malayalam script** rather than
  replaced with Sanskritic coinages: പാത്തോളജിസ്റ്റ്, ടിഷ്യു, സ്റ്റെയിൻ. This is how
  Malayalam medical writing actually works; കല for tissue is
  dictionary-correct but reads as literary Malayalam, not as something a
  pathologist would say at a microscope.
- **Numerals stay Latin.** ml-IN formats this way by default, and Malayalam
  numerals would look archaic on a lab report.
- **No plural agreement.** Malayalam does not mark it on counted nouns, so
  `relativeTime` takes the lookup function rather than formatting English and
  translating afterwards.

Typography: `--font-sans` lists `Inter` first and `Anek Malayalam` second.
Font matching happens per glyph, so Latin characters render in Inter and
Malayalam characters fall through to Anek Malayalam — one stack, correct for
a bilingual interface where technical terms sit inside a Malayalam sentence.
`:root[lang="ml"]` relaxes line-height and drops the tight Latin tracking and
uppercasing, neither of which suits Malayalam conjuncts.

### Translation review status

The UI chrome is safe to ship. **The four caveat texts and the safety banner
carry clinical meaning and should be signed off by a Malayalam-speaking
pathologist** before this is shown to patients or defended in a viva. They
read correctly, but a mistranslation there is the one that would actually
matter.

Caveats served by a real backend are shown verbatim and are never translated
client-side — the screen and the exported PDF must not be able to disagree
about what the tool claims. Only demo-mode caveats come from the string
table. See `src/i18n/caveats.js`.

## Sign-in

The demo account is hardcoded on the client, in `src/state/AuthContext.jsx`:

```
pathologist@gmck.edu.in  /  her2demo
```

It is printed on the login screen on purpose. It authenticates nobody and
protects nothing — anyone can read it out of the bundle. Replace it with a
server-issued session before this portal goes near a real slide.

## What is where

```
src/
  main.jsx              providers + mount
  App.jsx               routes, auth gate
  components/
    AppShell.jsx        sidebar + topbar + standing safety strip
    Sidebar.jsx         nav, live checkpoint status
    Topbar.jsx          search, theme toggle, account menu
    Icon.jsx            the whole icon set, no icon package
    charts/Charts.jsx   donut, stacked bar, compare bars, columns, sparkline
  pages/
    Login.jsx           hardcoded demo sign-in
    Dashboard.jsx       KPIs, current field, throughput, recent sign-offs
    Analysis.jsx        the working screen (see below)
    Cases.jsx           sign-off history, filter + search
    ModelCard.jsx       specification, limitations, AIM-HER2 comparison
    Method.jsx          the four caveats, pipeline, data handling
  state/                auth, theme, toasts, shared portal state
  lib/
    api.js              backend calls, with the demo fallback
    demo.js             deterministic synthetic fields and measurements
    format.js           percentages, dates, initials, dominant class
  styles/               tokens -> base -> app
legacy/                 the original index.html, app.js, styles.css
```

## Two decisions worth knowing about

**The headline number is a measurement, not a score.** The AIM-HER2 viewer this
layout borrows from shows "Algorithm Score: 2+ — do you accept?". This model
does not produce a score, so the Key Result block shows the largest
stained-area class, labelled as exactly that, with the "this is not a HER2
score" caveat immediately underneath. The safety strip repeats it on every
screen, and the caveats from `/api/context` are reprinted on the analysis page
rather than living only on a documentation page a click away.

**Demo data is always labelled.** `lib/api.js` degrades to `lib/demo.js` only
when the backend is genuinely unreachable; a real error response from the
server is surfaced as an error instead. Everything the demo module produces is
tagged `demo: true` and rendered with a visible badge, so a synthetic field can
never be mistaken for a real one. The PDF report has no demo equivalent — it
reports honestly that the backend is needed.

## Not a medical device

Final-year project, developed with Government Medical College Kottayam.
Research and workflow-support use only. Not validated for diagnostic use.

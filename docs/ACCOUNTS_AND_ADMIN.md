# Accounts and the admin console

BioMarkHER2 has real accounts. Everyone who uses the portal signs in with
their own email address and password, what they can do depends on their
role, and an administrator manages all of it from the **admin console**
(`/admin`). Every sign-in, account change, setting change and data export is
written to an audit log that only administrators can read.

This replaces the browser-only demo login the portal started with. That demo
login survives only in the static build on Netlify, which has no server to
authenticate against. There, the admin console runs on clearly labelled demo
data and protects nothing.

- Server code: [`app/auth.py`](../app/auth.py) (accounts, sessions, audit) and
  [`app/server.py`](../app/server.py) (routes and permission checks)
- Terminal tool: [`app/admin_cli.py`](../app/admin_cli.py) (`biomark-admin`)
- Portal: `ui/src/pages/admin/`, `ui/src/state/AuthContext.jsx`
- Tests: [`tests/test_auth.py`](../tests/test_auth.py) (53 tests)

---

## Roles

| Role | Can | Cannot |
|---|---|---|
| **Administrator** | Everything a pathologist can, plus the admin console | Change their own role, disable or delete themselves |
| **Pathologist** | Analyse fields, record assessments, mark regions, download reports | Open the admin console |
| **Viewer** | Analyse fields, download reports | Record an assessment or mark a region |

The server checks the role on every API request. The portal hides controls a
role can't use (a viewer sees why the sign-off panel is locked), but that's
a convenience. The server check is what enforces it.

Assessments and region annotations are signed with the **signed-in
account's** name, id and registration number, taken from the session. The
request body can't claim to be someone else.

---

## First run

1. Start the portal as usual:

   ```bash
   biomark
   ```

2. With no administrator yet, the server prints a one-time setup link and
   opens it in the browser:

   ```
   No administrator account exists yet. Create the first one here
   (this link works once, and only until the server restarts):

     http://127.0.0.1:8000/setup?token=…
   ```

3. Fill in your name, email and a password. You're signed in as the first
   administrator and taken to **Users**, ready to add your team.

The token lives only in the server's memory and is printed only to its own
console. Creating the first account therefore needs access to that console,
not just a network path to the server.

**No browser on the server?** Create the first administrator from a terminal:

```bash
biomark-admin create-admin --email you@hospital.org --name "Dr. A. Menon"
```

---

## Everyday tasks

### Add a person
**Admin console → Users → Add user.** Give their name, email and role (and
optionally their registration number and job title). Then choose how they
sign in the first time:

- **Set a password.** You choose it; *Generate* makes a strong one. By
  default they must replace it with their own at first sign-in. The next
  screen shows the portal address, email and password once, ready to copy.
  Send the password separately from the email address if you can.
- **Send an invite link.** They choose their own password. The link works
  once, for 72 hours. There is no email server, so copy the link and send it
  yourself.

### Access requests
With **Settings → Allow access requests** on (the default), people can ask
for an account from the sign-in page. A request waits as *Awaiting approval*
and appears under **Overview → Needs attention**. Approve it with a role, or
reject it. A pending account can't sign in. The form gives the same answer
for an address that already has an account, so it can't be used to find out
who has one.

### Forgotten password
Open the user, then either **Set a temporary password** (their sessions end,
and they choose a new one at next sign-in) or **Create a password link**
(single use, 24 hours; a new link cancels the old one).

### Locked account
After 5 failed sign-ins in a row (configurable) an account locks for 15
minutes (configurable). It shows as *Locked*, and in **Needs attention** with
an **Unlock** button. Unknown email addresses are throttled exactly like real
ones, so the lockout message doesn't reveal whether an account exists.

### Someone leaves, or a device is lost
- **Disable** the account: they're signed out everywhere at once and can't
  sign in. Their assessments stay in the log under their name.
- **Delete** it for good (you type their email to confirm).
- **Sessions** lists every signed-in device (browser, OS, IP address, last
  activity) with a **Sign out** button for each.

### Announcements
**Settings → Announcement banner** shows a message at the top of every page,
for example planned maintenance. Leave it empty to hide it.

### Audit log and exports
**Audit log** can be filtered by sign-ins, accounts, security, settings or
exports, by time range and by free text, and exported to CSV. **System**
downloads the users (CSV), the audit log (CSV), the review log (JSONL) and
the region annotations (JSONL). Every download is itself audited.

### Deployment readiness
**System → Deployment readiness** checks what's worth fixing before the
portal is used beyond one machine:
- at least two active administrators
- HTTPS with secure cookies when served over a network
- a model loaded
- uncertainty calibration present and current
- a built portal

---

## Settings

| Setting | Default | Range |
|---|---|---|
| Portal name | BioMarkHER2 | 1–60 characters |
| Announcement banner | *(empty)* | up to 280 characters |
| Sign out after inactivity | 60 min | 5–1440 |
| Longest session | 12 hours | 1–720 |
| Allow "Keep me signed in" | on | on/off |
| Remembered sessions last | 7 days | 1–90 |
| Minimum password length | 10 | 8–64 |
| Lock after failed attempts | 5 | 3–20 |
| Lock for | 15 min | 1–1440 |
| Allow access requests | on | on/off |

Every change is recorded in the audit log with its old and new value.

---

## How it's protected

| | |
|---|---|
| **Passwords** | scrypt (N=2¹⁴, r=8, p=1), a random salt per password, parameters stored with each hash. Never stored, logged or returned in plain text. The policy is length (NIST SP 800-63B) plus rejecting common passwords, the email address, and strings with too few distinct characters. No composition rules. |
| **Sessions** | A random 256-bit token in an `HttpOnly; SameSite=Strict` cookie (`Secure` with `--secure-cookies`). The database stores only its SHA-256, so a copy of the file can't be replayed as a login. Sessions end after inactivity, at a maximum age, on sign-out, on a password change (other devices), and when the account is disabled or deleted. |
| **CSRF** | Every state-changing request must carry the session's CSRF token in `X-CSRF-Token`. Request bodies must be JSON, which a cross-site HTML form can't send. |
| **Guessing** | Per-account lockout, per-IP throttling of failed sign-ins, and throttled access requests. Unknown emails behave exactly like real ones. |
| **Enumeration** | Wrong password and unknown email get the same answer. A disabled or pending account is named only when the password was right. |
| **Admin mistakes** | The last active administrator can't be demoted, disabled or deleted. Nobody can change their own role or status. |
| **One-time links** | Stored as hashes, single use, expiring. The token is removed from the address bar as soon as the page reads it, and redacted from the server's console log. `Referrer-Policy: same-origin` keeps it from leaking to third-party hosts. |
| **Headers** | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cache-Control: no-store`, and HSTS when served over HTTPS. |
| **Audit** | Every sign-in (successful or not), lockout, sign-out, session ended, account created, changed, approved or deleted, password set or reset, link created, setting changed and export. Each records who did it, to whom, from which IP address and when. |

Accounts live in `artifacts/biomark.db` (SQLite; change with `--db` or
`BIOMARK_DB`). `artifacts/` is gitignored and is the directory
docker-compose already mounts, so accounts survive container rebuilds.
**Back this file up** with the review log.

---

## Serving it to other people

The server speaks plain HTTP and binds to `127.0.0.1` by default. To let other
machines use it, put it behind a reverse proxy that terminates HTTPS, and
start it with:

```bash
biomark --host 0.0.0.0 --secure-cookies --trust-proxy --no-browser
```

| Flag | Environment variable | Why |
|---|---|---|
| `--secure-cookies` | `BIOMARK_SECURE_COOKIES=1` | Session cookie marked `Secure`; HSTS sent. Required behind HTTPS. |
| `--trust-proxy` | `BIOMARK_TRUST_PROXY=1` | Audit log and throttling use the client's address from `X-Forwarded-For` rather than the proxy's. Only behind a proxy you control. |
| `--db PATH` | `BIOMARK_DB` | Where the account database lives. |

A minimal Caddy configuration (HTTPS certificates are automatic):

```
her2.your-hospital.org {
    reverse_proxy 127.0.0.1:8000
}
```

or nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    client_max_body_size 25m;   # uploaded fields are up to 24 MB
}
```

The server prints a warning at start-up if it's bound beyond this machine
without `--secure-cookies`.

---

## Recovery from a terminal

```bash
biomark-admin list-users
biomark-admin reset-password --email someone@hospital.org   # temporary password, must be changed
biomark-admin unlock --email someone@hospital.org
biomark-admin create-admin --email new-admin@hospital.org --name "Dr. B. Nair"
```

Passwords are read from a hidden prompt (or `--password-stdin` for scripts),
never from the command line where they would land in shell history. Use
`--db` for a database other than `artifacts/biomark.db`.

---

## The demo build (Netlify)

The static build has no backend, so the portal falls back to its browser-only
demo:
- The demo account (`pathologist@gmck.edu.in` / `her2demo`) signs in as an
  administrator.
- The admin console runs on a seeded in-browser store (ten fictional users
  on `example.org`, a few days of activity), with a **Demo data** banner and a
  *Reset demo data* button.
- It imitates the server's rules (last administrator, no self-demotion,
  password length) so it can be demonstrated end to end, but it protects
  nothing. The Netlify site's own password gate
  (`ui/netlify/edge-functions/gate.ts`) is what keeps it private.

---

## API

All request bodies are JSON. Routes marked 🔒 need a session. Every POST,
PATCH or DELETE under a session needs `X-CSRF-Token`.

| Method | Route | |
|---|---|---|
| GET | `/api/auth/config` | Setup needed? Access requests on? Password length, … |
| GET | `/api/auth/me` | The signed-in user, permissions and CSRF token, or `{"user": null}` |
| POST | `/api/auth/login` | `{email, password, remember}` |
| POST | `/api/auth/setup` | `{token, name, email, password}`: the first administrator |
| POST | `/api/auth/request-access` | `{name, email, password, registration, title, note}` |
| POST | `/api/auth/link/inspect` · `/api/auth/link` | Check / use an invite or reset link |
| POST 🔒 | `/api/auth/logout` · `/api/auth/password` | Sign out · change own password |
| PATCH 🔒 | `/api/auth/profile` | Own name, registration, job title, avatar colour |
| GET/DELETE 🔒 | `/api/auth/sessions[/{id}]` · POST `/api/auth/sessions/revoke-others` | Own sessions |
| GET 🔒 | `/api/admin/overview` · `/api/admin/system` | Console overview · system facts and checks |
| GET/POST 🔒 | `/api/admin/users` | List (`?q=&role=&status=`) · create (`access: password \| invite`) |
| GET/PATCH/DELETE 🔒 | `/api/admin/users/{id}` | One account: detail, sessions and activity · update · delete |
| POST 🔒 | `/api/admin/users/{id}/password` · `/link` · `/unlock` · `/sign-out` · `/approve` | Account actions |
| GET/DELETE 🔒 | `/api/admin/sessions[/{id}]` | Every session · end one |
| GET 🔒 | `/api/admin/audit` (`?category=&days=&q=&before=&limit=`) · `/api/admin/audit.csv` | Audit log |
| GET/PATCH 🔒 | `/api/admin/settings` | Settings |
| GET 🔒 | `/api/admin/users.csv` · `/api/admin/export/{reviews,annotations}.jsonl` | Exports |

The clinical routes keep their paths and now need a role:
- `GET /api/context` and `/api/reviews`, `POST /api/analyze` and `/api/report`: any role
- `POST /api/review` and `/api/annotations`: pathologist or administrator

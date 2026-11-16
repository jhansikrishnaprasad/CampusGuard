# Deployment guide: local Windows app vs. public hosted app

**Honest status of this release:** the hosted deployment is **prepared but NOT deployed and NOT tested**. Publishing a public URL needs a server/domain
account and your approval, and the build environment had no internet or Docker. `Dockerfile`, `docker-compose.yml` and `Caddyfile` are ready to use
following the steps below; run the checklist in section 6 before telling anyone the URL is live.

## 1. Two ways to run CampusGuard
| | **A. Local Windows executable** | **B. Central hosted application** |
|---|---|---|
| Who uses it | One person on one computer | Faculty/students on their own devices through a browser |
| How | `CampusGuard.exe` (or `run.ps1`) -> http://127.0.0.1:8000 | `https://campusguard.<your-domain>` |
| Network exposure | None: listens on `127.0.0.1` only | Public internet through an HTTPS reverse proxy |
| Login | Off by default (single local user) | **Mandatory** (`CAMPUS_REQUIRE_LOGIN=true`) |
| Data location | `%LOCALAPPDATA%\CampusGuard` (outside the program folder) | Docker volume `campusguard_data` on the server |
| Video processing | Uses that PC's CPU | Uses the **server's** CPU - must be sized for it |
| Best for | Demonstrations, individual use, offline use | Shared review of footage by several staff |

## 2. Hosting options (evaluate current terms yourself; prices/limits change)
| Option | FastAPI | Background video jobs | Persistent disk | Large uploads (GBs) | HTTPS | Verdict |
|---|---|---|---|---|---|---|
| **Free PaaS tiers** (Render/Railway/Fly/Hugging Face Spaces style) | yes | usually CPU- and memory-capped, may sleep when idle | often **ephemeral** or tiny | request-size/time limits are common | yes | **Not suitable** for CCTV analysis; fine only for a UI demo with synthetic data. Check each provider's current limits before assuming otherwise |
| **Small VPS / cloud VM** (any provider: AWS Lightsail/EC2, Azure, DigitalOcean, Hetzner, Oracle...) | yes | yes (you control CPU/RAM) | yes (attached disk) | yes (you set limits) | yes via Caddy | **Recommended.** Start at 4 vCPU / 8 GB RAM / 100+ GB disk and measure seconds of processing per footage-minute with `scripts/evaluate.py` |
| **College/department server** | yes | yes | yes | yes | needs IT-provided certificate or a tunnel | Good if IT approves; also best for privacy (footage stays on campus) |
| **Cloudflare Tunnel / similar tunnel** to a machine you own | yes | yes | yes | tunnel upload limits apply (check) | yes, no open ports | Good for **demo day** |
| **ngrok-style temporary URL** | yes | yes | yes | limited | yes | Demos only; the URL changes |

## 3. Recommended architecture (option B)
```
Internet --HTTPS (443)--> Caddy (automatic certificate, 4 GB body limit) --private Docker network--> CampusGuard (uvicorn, ONE worker) --> SQLite (WAL) + files on a volume
```
* The app container's port is **not published**; only Caddy exposes 80/443. Never expose `uvicorn` directly to the internet.
* **One worker only**: the analysis job manager is an in-process thread.
* `COOKIE_SECURE=true`, `CAMPUS_REQUIRE_LOGIN=true`, a strong `ADMIN_PASSWORD`; the admin creates reviewer accounts (`POST /api/auth/users`).
* Auth on every video/evidence/report endpoint, upload validation (extension, signature, decodability, size, duration), path-traversal-safe file serving,
  same-origin check on writes, login throttling, audit log - all already in the code (see README "Security").

### Is SQLite appropriate?
Yes for **one server instance with a handful to a few dozen occasional users** (WAL mode, short transactions, single worker). It stops being appropriate if
you need several app instances, high-concurrency writes or managed HA. The switch would be **PostgreSQL**; because `app/migrations.py` is SQLite-specific, that
needs Alembic migrations and a data-migration script. **That changes the approved stack, so it is not done here - approval is required first.**

## 4. Steps to deploy (VPS with Docker)
1. Create a Linux VM (Ubuntu LTS), open ports 80 and 443 only, point a DNS **A record** (e.g. `campusguard.yourcollege.edu`) at its IP.
2. Install Docker + the compose plugin; copy the project folder (the source ZIP) to the server.
3. `cp .env.deploy.example .env` -> set `DOMAIN` and a long random `ADMIN_PASSWORD`.
4. `docker compose up -d --build` (first start also obtains the HTTPS certificate).
5. Open `https://<DOMAIN>`, sign in as admin, create reviewer accounts, upload a short test video.
6. Backups: Settings -> Backup (database) and copy the volume (`docker run --rm -v campusguard_data:/data -v $PWD:/b busybox tar czf /b/campusguard_data.tgz /data`).
7. Updates: `git pull && docker compose up -d --build` - the volume (database, videos, evidence) is untouched and old databases are migrated with an automatic backup.

## 5. Privacy and legal checklist (CCTV of people is personal data)
Obtain institutional approval and a documented purpose; restrict accounts to authorised reviewers; set retention (Settings -> retention, default 90 days video / 180 days
evidence); never publish real footage, evidence or databases to GitHub; tell the faculty that findings are predictions that need human review; keep the host's disk encrypted if the policy requires it.

## 6. Go-live verification checklist (not yet executed)
- [ ] `https://<DOMAIN>` loads with a valid certificate and redirects HTTP to HTTPS
- [ ] Unauthenticated `GET /api/dashboard` returns 401
- [ ] Upload a 1 GB test file succeeds (proxy limits), an invalid file is rejected
- [ ] Analysis completes; restart `docker compose restart` and data persists
- [ ] `docker compose ps` shows app healthy; backup restores on a spare machine

## 7. Quick demo for faculty without renting a server (temporary public link)
Run CampusGuard on your PC and expose it through a tunnel for the duration of the demo only. **Turn login ON first**: the local exe/`run.ps1` default is *no password*,
so an unprotected tunnel would give the whole internet administrator access. In `.env` (or `%LOCALAPPDATA%\CampusGuard\.env` for the exe) set
`CAMPUS_REQUIRE_LOGIN=true`, `COOKIE_SECURE=true` and `ADMIN_PASSWORD=<long random password>` **before the first start**, then run the app and, for example, Cloudflare's quick tunnel
(`cloudflared tunnel --url http://127.0.0.1:8000`, see Cloudflare's current documentation). Share the printed `https://...` address and the password only with the faculty, and stop the tunnel afterwards.
If the app already started once, the first administrator password is already fixed: set a new one with `.\.venv\Scripts\python scripts\reset_admin_password.py` (run from source) before sharing the link.
Your PC must stay on, and the link is temporary. This is a demo aid, not a permanent deployment.

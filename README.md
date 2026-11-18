<div align="center">

# KTU Notifications API

**Unofficial REST API for KTU announcements and notifications, served as clean JSON.**

Real-time circulars, exam notices and notifications from [APJ Abdul Kalam Technological University (KTU)](https://ktu.edu.in), with attachments pre-cached as downloadable PDFs.

[![Scraper](https://github.com/ratherpixelate/ktu-announcements-api/actions/workflows/scraper.yml/badge.svg)](https://github.com/ratherpixelate/ktu-announcements-api/actions/workflows/scraper.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/built%20with-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)

[**Live API**](https://ktu-announcements-api-wxk8.onrender.com) · [**Interactive Docs**](https://ktu-announcements-api-wxk8.onrender.com/docs) · [**Report a Bug**](https://github.com/ratherpixelate/ktu-announcements-api/issues)

</div>

> **Disclaimer:** This is an independent, community-maintained project. It is not affiliated with, endorsed by, or connected to APJ Abdul Kalam Technological University. Data is sourced from the public [KTU announcements page](https://ktu.edu.in/Menu/announcements) for educational and developer use. Always confirm important notices on the official portal.

---

## Table of contents

- [Why this API](#why-this-api)
- [Quick start](#quick-start)
- [API reference](#api-reference)
- [Data model](#data-model)
- [How scheme detection works](#how-scheme-detection-works)
- [Architecture](#architecture)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Project structure](#project-structure)
- [Limitations](#limitations)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

---

## Why this API

KTU publishes its notifications on a portal protected by Cloudflare Turnstile, which makes the data hard to consume from scripts, bots and apps. This project drives a real anti-detect browser to pass the check and republishes the data as a simple, CORS-enabled JSON API.

- **Free and open:** no API key or authentication needed for read endpoints.
- **Fresh:** the scraper runs every 30 minutes via GitHub Actions, and on demand through a protected endpoint.
- **Structured:** each announcement has an ID, title, date, "new" flag, attachments, plain-text and HTML descriptions, and the KTU scheme(s) it applies to.
- **Filterable:** limit the result count, show only new announcements, or filter by scheme (`2015`, `2019`, `2024`, `General`).
- **PDF attachments:** recent attachments are pre-cached and downloadable directly with their original filenames.
- **Browser-friendly:** CORS is open to all origins, so you can call it from any frontend.
- **Fast and lightweight:** all data is served from memory, with no browser running on the API server (~38 MB RAM on Render).
- **Resilient:** a bundled snapshot of recent announcements means the API responds immediately after a cold start, even before the first sync.

**Typical uses:** Telegram/Discord/WhatsApp notifier bots, student dashboards, mobile apps, RSS bridges, and campus notification feeds.

---

## Quick start

**Base URL:** `https://ktu-announcements-api-wxk8.onrender.com`

```bash
# Latest 5 announcements
curl "https://ktu-announcements-api-wxk8.onrender.com/announcements?limit=5"
```

**Python**

```python
import requests

BASE = "https://ktu-announcements-api-wxk8.onrender.com"
data = requests.get(f"{BASE}/announcements", params={"limit": 5}).json()

for item in data["data"]:
    print(item["date"], item["title"])
```

**JavaScript**

```js
const BASE = "https://ktu-announcements-api-wxk8.onrender.com";
const res = await fetch(`${BASE}/announcements?scheme=2019&limit=5`);
const { data } = await res.json();
data.forEach((a) => console.log(a.date, a.title));
```

**Detect new announcements (polling sketch for a bot)**

```python
import time
import requests

BASE = "https://ktu-announcements-api-wxk8.onrender.com"
seen = {a["id"] for a in requests.get(f"{BASE}/announcements").json()["data"]}

while True:
    time.sleep(15 * 60)  # data refreshes every ~30 minutes
    for a in requests.get(f"{BASE}/announcements").json()["data"]:
        if a["id"] not in seen:
            seen.add(a["id"])
            print("New:", a["title"])
```

> The service runs on a free-tier host, so the first request after a period of inactivity may be slow while the instance wakes up.

---

## API reference

Interactive documentation (Swagger UI) is available at [`/docs`](https://ktu-announcements-api-wxk8.onrender.com/docs).

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/` | GET | none | Landing page with live service status |
| `/announcements` | GET | none | List cached announcements, with optional filters |
| `/announcements/{id}` | GET | none | Get a single announcement by its exact ID |
| `/download/{encrypt_id}` | GET | none | Download a pre-cached attachment as a PDF |
| `/health` | GET | none | Service status and cache information |
| `/refresh` | GET | secret | Trigger an on-demand scrape (10-minute cooldown) |
| `/api/sync` | POST | `X-Sync-Secret` | Scraper data-ingestion endpoint (internal) |
| `/docs` | GET | none | Swagger UI / OpenAPI documentation |

### `GET /announcements`

| Query parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | integer | none | Maximum number of announcements to return (applied after the other filters) |
| `new_only` | boolean | `false` | Only return announcements KTU has marked as new |
| `scheme` | string | none | Filter by scheme (`2015`, `2019`, `2024`). Announcements tagged `General` are always included |

Announcements are returned in the order KTU lists them. If `scheme` is set to a value no announcement is tagged with, only `General` announcements are returned. Announcements whose scheme could not be determined (empty `schemes` list) only appear when you are not filtering by scheme.

```bash
curl "$BASE/announcements"
curl "$BASE/announcements?limit=5"
curl "$BASE/announcements?new_only=true"
curl "$BASE/announcements?scheme=2019"
curl "$BASE/announcements?scheme=2024&new_only=true&limit=3"
```

**Response** (`Cache-Control: public, max-age=300`)

```json
{
  "success": true,
  "count": 1,
  "last_updated": "2026-11-16T11:50:07.472691Z",
  "data": [
    {
      "id": "5561",
      "title": "M.Arch/M.Plan S1 (S,FE ) Examination November 2026,(2016 Scheme) Notified",
      "description_html": "<p>It is hereby informed that Exam Registration for ... are opened in the portal, as scheduled below:-</p>",
      "description_text": "It is hereby informed that Exam Registration for ... are opened in the portal, as scheduled below:-",
      "date": "2026-11-13",
      "is_new": false,
      "attachments": [
        { "name": "Notification", "encrypt_id": "AAAefQ==" }
      ],
      "schemes": ["2015"],
      "scraped_at": "2026-11-16T11:50:07.472691Z"
    }
  ]
}
```

### `GET /announcements/{id}`

Returns one announcement object (same shape as an item in `data` above), or `404` with `{"detail": "Announcement not found"}`. The cache control header is `public, max-age=300`.

```bash
curl "$BASE/announcements/5561"
```

### `GET /download/{encrypt_id}`

Streams an attachment as `application/pdf` with `Content-Disposition: attachment` and its original filename (`Cache-Control: public, max-age=86400`). Use the `encrypt_id` from an announcement's `attachments` list.

```bash
# -O -J saves the file under its original filename
curl -O -J "$BASE/download/AAAefQ=="
```

Only attachments held in the server's cache can be downloaded. For anything else the API returns `404` with context:

```json
{
  "detail": {
    "error": "Attachment not found in cache",
    "message": "KTU enforces per-request Cloudflare Turnstile verification. ...",
    "encrypt_id": "...",
    "announcement": "Title of the related announcement, or null",
    "official_portal_url": "https://ktu.edu.in/Menu/announcements"
  }
}
```

### `GET /health`

Service status and cache information (`Cache-Control: public, max-age=60`).

```json
{
  "status": "online",
  "cached_items": 10,
  "last_updated": "2026-11-16T11:50:07.472691Z",
  "last_attempt": "2026-11-16T11:50:07.472691Z",
  "last_error": null,
  "has_token": true
}
```

| Field | Meaning |
|---|---|
| `cached_items` | Number of announcements currently in memory |
| `last_updated` | When the announcements were last successfully refreshed |
| `last_attempt` | When the last sync or scrape attempt happened |
| `last_error` | Message from the last failed attempt, or `null` |
| `has_token` | Whether a KTU session token is currently held (the token itself is never exposed) |

### `GET /refresh`

Triggers an immediate scrape without waiting for the 30-minute schedule. In the default decoupled mode this dispatches the GitHub Actions workflow, so it needs a secret and a GitHub token configured on the server.

Provide the secret by any one of:

- `X-Refresh-Secret: <secret>` header (preferred; keeps it out of URLs and logs)
- `Authorization: Bearer <secret>` header
- `?secret=<secret>` query parameter

```bash
curl -H "X-Refresh-Secret: YOUR_SECRET" "$BASE/refresh"
```

| `status` in response | Meaning |
|---|---|
| `online` with `auth_required: true` | No or wrong secret; returns cache info and a hint, nothing is dispatched |
| `dispatched` | Workflow dispatched; the cache updates in about 1-2 minutes |
| `cooldown` | A dispatch happened in the last 10 minutes; `cooldown_remaining_seconds` says how long to wait |
| `error` | `GITHUB_PAT` is missing, GitHub rejected the dispatch, or GitHub could not be reached |

In standalone mode (`ENABLE_IN_CONTAINER_SCRAPER=true`), `/refresh` runs a scrape in-process and returns `status: online`, `mode: in-container`.

### `POST /api/sync`

Internal endpoint used by the GitHub Actions scraper to push fresh data. It requires the `X-Sync-Secret` header to match the server's `SYNC_SECRET` (otherwise `403`).

| Payload field | Type | Description |
|---|---|---|
| `announcements` | list of [Announcement](#data-model) | Replaces the cached announcements when non-empty |
| `x_token` | string, optional | KTU session token |
| `cached_attachments` | list, optional | Items of `{encrypt_id, filename, content_b64}`; merged into the attachment cache |

The attachment cache keeps at most the 25 most recent files, to bound memory usage. A successful call returns `status`, `synced_items`, `cached_attachments`, `has_token` and `last_updated`.

---

## Data model

**Announcement**

| Field | Type | Description |
|---|---|---|
| `id` | string | KTU's announcement ID |
| `title` | string | Announcement subject |
| `description_html` | string \| null | Original HTML message body, if any |
| `description_text` | string \| null | Plain-text version of the body |
| `date` | string (`YYYY-MM-DD`) | Announcement date |
| `is_new` | boolean | `true` when KTU flags it as new |
| `attachments` | list of Attachment | Attached documents (can be empty) |
| `schemes` | list of string | Schemes the notice applies to: `"2015"`, `"2019"`, `"2024"`, `"General"`, or empty if undetermined |
| `scraped_at` | string (ISO 8601, UTC) | When this record was scraped |

**Attachment**

| Field | Type | Description |
|---|---|---|
| `name` | string | Display title of the document |
| `encrypt_id` | string | ID to pass to [`/download/{encrypt_id}`](#get-downloadencrypt_id) |

---

## How scheme detection works

KTU has run several syllabus schemes side by side (currently `2015`, `2019` and `2024`), and many notices apply to only one of them. Because KTU does not tag announcements by scheme, the API infers it with a small rule-based parser (`app/utils.py`):

1. **Explicit mentions:** text such as "2019 scheme" or "2024 admission" is used directly. Other years map to the latest known scheme that is not newer than that year (for example, "2020 Scheme" maps to `2019`).
2. **General notices:** if the text mentions no degree (B.Tech, M.Tech, B.Arch, M.Arch, MCA, MBA, PhD) and no semester (S1 to S8), the notice is tagged `General`.
3. **Safety check:** supplementary, supply, mercy chance and part-time notices are left untagged (`[]`) rather than guessed.
4. **Calculation for B.Tech:** for B.Tech and inter-college transfer notices that mention a semester, the parser works out the likely admission year from the academic year in the text (for example, "AY 2026-27") or, failing that, from the publish date, then maps it to a scheme.
5. **Otherwise:** the notice is left untagged (`[]`).

This is a best-effort heuristic. Always check the attached notice for anything important.

---

## Architecture

The service is split in two so that the API stays tiny and the heavy browser work happens elsewhere. This lets it run reliably on constrained hosts such as Render's 512 MB free tier.

```
+---------------------------------------+
|         GitHub Actions Runner         |
|   - Runs every 30m / on-demand        |
|   - Headless Camoufox browser         |
|   - Solves Cloudflare Turnstile       |
|   - Intercepts API response & token   |
|   - Pre-fetches PDF attachments       |
+-------------------+-------------------+
                    |
                    | POST /api/sync (X-Sync-Secret)
                    v
+---------------------------------------+
|          FastAPI Application          |
|   - Render web service                |
|   - In-memory data & PDF cache        |
|   - No browser on the API server      |
|   - Protected /refresh endpoint       |
+---------------------------------------+
```

1. **Scheduled scrape:** the GitHub Actions workflow (`.github/workflows/scraper.yml`) runs every 30 minutes. It also runs on manual dispatch and on pushes to `main` (ignoring README, LICENSE, `docs/` and `.gitignore` changes).
2. **Browser scraping:** `scripts/sync_to_render.py` calls the scraper (`app/scraper.py`), which launches a headless [Camoufox](https://camoufox.com/) browser (an anti-detect Firefox build driven through Playwright). It opens the KTU announcements page, clicks through any interactive Turnstile challenge, and intercepts the portal's own JSON response and session token.
3. **Parsing:** HTML descriptions are converted to plain text with BeautifulSoup, dates are parsed, and schemes are inferred.
4. **Attachment pre-caching:** while the Turnstile-verified session is live, the scraper triggers each attachment download in the browser and keeps only responses that decode to a valid PDF. Attachments already known from `data/seed_attachments.json` are skipped, so only new ones cost a fetch. Up to 25 are kept.
5. **Sync:** the runner `POST`s announcements, token and PDFs to `/api/sync` on the API server, retrying once on failure.
6. **Serving:** FastAPI serves everything from memory. On startup it loads a bundled snapshot (`data/seed_announcements.json` and `data/seed_attachments.json`) so responses work right away.
7. **On-demand refresh:** `/refresh` dispatches the same workflow through the GitHub API, guarded by a secret and a 10-minute cooldown.

### Scraper reliability

- Up to **3 attempts**, each waiting up to **80 seconds** for the portal response.
- Detects **KTU backend outages** (HTTP 5xx or failed requests) and reports them distinctly from scraper failures. While KTU is down, the last good data stays served.
- On total failure it saves `scraper_failure.png` and `scraper_failure.html`, which the workflow uploads as a build artifact for debugging.
- In standalone mode, a **180-second watchdog** stops a hung scrape.

---

## Local development

**Requirements:** Python 3.12+, and optionally [uv](https://docs.astral.sh/uv/) and Docker.

```bash
git clone https://github.com/ratherpixelate/ktu-announcements-api.git
cd ktu-announcements-api

# Install dependencies
uv sync                       # or: pip install -r requirements.txt
```

### Option 1: API only (decoupled mode, recommended)

Runs the FastAPI service with no browser. It starts with the bundled snapshot data.

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> for the landing page and <http://localhost:8000/docs> for Swagger UI.

To fill your local cache with live data, install the scraper's browser once, start the API with a sync secret, and then run the scraper script against it:

```bash
# one-time: browser dependencies
playwright install-deps firefox
python -m camoufox fetch

# terminal 1: API with a sync secret
SYNC_SECRET=local_dev uv run uvicorn app.main:app --port 8000

# terminal 2: scrape KTU and push the result to your local API
RENDER_API_URL=http://localhost:8000 SYNC_SECRET=local_dev uv run python scripts/sync_to_render.py
```

### Option 2: Standalone mode (scraper inside the API process)

Runs the API and a scheduled scraper together via APScheduler (scrapes at startup, then every 30 minutes). Requires the browser setup above.

```bash
ENABLE_IN_CONTAINER_SCRAPER=true uv run uvicorn app.main:app --port 8000
```

Set `CAMOUFOX_HEADLESS=false` to watch the browser while debugging, or `virtual` for a virtual display.

### Option 3: Docker

```bash
docker build -t ktu-announcements-api .
docker run -p 8000:8000 -e PORT=8000 -e SYNC_SECRET=local_dev ktu-announcements-api
```

The image is API-only and does not bundle the Camoufox browser, so it runs in decoupled mode. Without `PORT` it falls back to port `8000`.

### Tests

```bash
uv run pytest        # or: pytest
```

The suite covers the endpoints, filters, caching and attachment pruning, sync and refresh authorization, seed loading, and the scheme-detection rules.

---

## Configuration

| Variable | Used by | Description |
|---|---|---|
| `SYNC_SECRET` | API server, Actions | Shared secret protecting `/api/sync`. Also accepted as the `/refresh` secret when `REFRESH_SECRET` is unset. Required for syncing |
| `REFRESH_SECRET` | API server | Optional separate secret for `/refresh`. Falls back to `SYNC_SECRET` |
| `GITHUB_PAT` (or `GH_TOKEN`) | API server | GitHub token allowed to dispatch workflows (fine-grained: Actions read/write; classic: `repo`). Required for `/refresh` dispatch |
| `GITHUB_REPO` | API server | Repository to dispatch, as `owner/repo`. Defaults to `ratherpixelate/ktu-announcements-api` |
| `RENDER_API_URL` | Scraper script | Base URL of the API server that receives the sync. If unset, the script scrapes but skips syncing |
| `ENABLE_IN_CONTAINER_SCRAPER` | API server | `true` or `1` turns on the in-process APScheduler scraper (standalone mode) |
| `CAMOUFOX_HEADLESS` | Scraper | `true` (default), `virtual`, or `false` / `0` |
| `PORT` | Container | HTTP port (defaults to `8000`; `render.yaml` sets `10000`) |

---

## Deployment

The reference setup is a Render web service for the API plus GitHub Actions for scraping, both on free tiers.

**1. API server on Render**

`render.yaml` defines a Docker web service on the free plan with `PORT`, `PYTHONUNBUFFERED` and an auto-generated `SYNC_SECRET`. Deploy it as a Blueprint, or create a Docker web service from this repository. To enable `/refresh`, also add `GITHUB_PAT` (and optionally `REFRESH_SECRET` and `GITHUB_REPO`) in the service's environment settings.

**2. Scraper on GitHub Actions**

In your repository's *Settings → Secrets and variables → Actions*, add:

| Secret | Value |
|---|---|
| `RENDER_API_URL` | Your Render service URL, for example `https://your-service.onrender.com` |
| `SYNC_SECRET` | The same value as the `SYNC_SECRET` on your Render service |

The workflow then scrapes every 30 minutes and syncs the result. Failed runs upload the diagnostic screenshot and HTML as an artifact.

---

## Project structure

```
.
├── app/
│   ├── main.py          # FastAPI app, routes, landing page
│   ├── scraper.py       # Camoufox scraper, Turnstile handling, attachment pre-fetch
│   ├── cache.py         # In-memory state, seed loading, APScheduler (standalone mode)
│   ├── models.py        # Pydantic models (Announcement, Attachment, SyncPayload, ...)
│   └── utils.py         # Scheme detection logic
├── data/
│   ├── seed_announcements.json   # Bundled snapshot for instant cold starts
│   └── seed_attachments.json     # Bundled PDF snapshot (base64)
├── scripts/
│   └── sync_to_render.py         # Scrape + push to the API server (used by Actions)
├── tests/
│   ├── test_api.py
│   └── test_utils.py
├── .github/workflows/scraper.yml # 30-minute scraper schedule
├── Dockerfile
├── render.yaml
├── pyproject.toml / uv.lock / requirements.txt
└── LICENSE
```

**Built with:** [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [Camoufox](https://camoufox.com/) + [Playwright](https://playwright.dev/), [httpx](https://www.python-httpx.org/), [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/), [APScheduler](https://apscheduler.readthedocs.io/), [python-dotenv](https://pypi.org/project/python-dotenv/), and [pytest](https://pytest.org/).

---

## Limitations

- **Data freshness:** updates are as frequent as the 30-minute schedule (GitHub's scheduler can run a few minutes late). KTU itself may be slow to publish.
- **Attachments:** only the most recent attachments (up to 25) are cached, because KTU requires a fresh Cloudflare Turnstile verification for every download. Older documents return `404`; use the official portal for those.
- **In-memory cache:** data lives in memory and is rebuilt from the bundled snapshot plus the next sync after a restart.
- **KTU outages:** if KTU's portal is down or changes its layout, the scraper may fail. The API keeps serving the last good data, and `/health` reports `last_error`.
- **Scheme tags are inferred** and may be empty or imperfect (see [How scheme detection works](#how-scheme-detection-works)).
- **Scope:** only the public announcements feed is covered, not student results or logins.
- **Cold starts:** free-tier hosting may sleep when idle, so the first request can take a while.

---

## FAQ

**Is this the official KTU API?**
No. It is an independent, unofficial project and is not affiliated with APJ Abdul Kalam Technological University.

**Is there an API for KTU notifications and announcements?**
Yes, this one. It exposes KTU's announcements (notifications, circulars, exam notices and more) as JSON at `/announcements`.

**Do I need an API key?**
No. All read endpoints are public. Only `/refresh` and `/api/sync` need a secret.

**How often is the data updated?**
Every 30 minutes through GitHub Actions. You can also trigger a scrape with `/refresh` if you host your own instance.

**Can I download the PDF attachments?**
Yes, for recent announcements. Use the `encrypt_id` from the announcement's `attachments` with `/download/{encrypt_id}`. Older attachments are not cached.

**Can I call it from a website or app?**
Yes. CORS is enabled for all origins.

**Can I self-host it?**
Yes. See [Local development](#local-development) and [Deployment](#deployment).

**Why does it use a browser to scrape?**
KTU's portal is protected by Cloudflare Turnstile, so plain HTTP requests are blocked. The scraper uses Camoufox, an anti-detect browser, to complete the verification.

**What do the values in `schemes` mean?**
`2015`, `2019` and `2024` are KTU syllabus schemes. `General` means the notice applies to everyone. An empty list means the scheme could not be determined.

**Does it support rate limits?**
There is no rate limiting on read endpoints. Please cache responses on your side (the API sends `Cache-Control` headers) and avoid aggressive polling; every ~15-30 minutes is plenty.

---

## Contributing

Issues and pull requests are welcome.

1. Fork the repository and create a branch.
2. Make your change and add or update tests in `tests/`.
3. Run `pytest` and make sure everything passes.
4. Open a pull request describing the change.

Commit messages follow the conventional style (`feat:`, `fix:`, `docs:`, `perf:`).

---

## License

Released under the [MIT License](./LICENSE).

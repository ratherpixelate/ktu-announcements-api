# KTU Announcements API

An unofficial REST API that scrapes and serves announcements from the [APJ Abdul Kalam Technological University (KTU)](https://ktu.edu.in) website. Built with **FastAPI**, **Camoufox** (anti-detect browser engine to bypass Cloudflare Turnstile), and **GitHub Actions** for automated decoupled scraping and pre-cached attachment serving.

> ⚠️ This is an unofficial, community-maintained project and is **not affiliated with APJ Abdul Kalam Technological University**.


## 🌐 Live API

The API is publicly hosted and ready to use:

**Base URL:** [https://ktu-announcements-api-wxk8.onrender.com](https://ktu-announcements-api-wxk8.onrender.com)

| Endpoint | Method | Description |
|---|---|---|
| `/announcements` | `GET` | Returns all cached announcements |
| `/announcements?limit=5` | `GET` | Returns the N most recent announcements |
| `/announcements?new_only=true` | `GET` | Returns only announcements marked as "New" |
| `/announcements?scheme=2019` | `GET` | Filters by scheme year (e.g. `2015`, `2019`, `2024`, or `General`) |
| `/announcements/{id}` | `GET` | Returns a specific announcement by its numeric ID |
| `/download/{encrypt_id}` | `GET` | Downloads an attached document directly as a PDF (pre-cached) |
| `/health` | `GET` | API status, token presence, and cache timestamp |
| `/refresh` | `GET` | Triggers an on-demand scraper dispatch (requires secret, 10m cooldown) |
| `/api/sync` | `POST` | Scraper sync endpoint (internal, requires `X-Sync-Secret`) |
| `/docs` | `GET` | Interactive Swagger UI documentation |


## 🛠️ Tech Stack

| Tool | Purpose |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | Web framework & API routing with automatic OpenAPI docs |
| [Camoufox](https://camoufox.com/) | Headless anti-detect browser engine (bypasses Cloudflare Turnstile) |
| [GitHub Actions](https://github.com/features/actions) | Scheduled runner (every 30m) for scraping and syncing |
| [httpx](https://www.python-httpx.org/) | High-speed async HTTP requests & PDF pre-fetching |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | HTML cleaning & plain-text extraction |
| [Uvicorn](https://www.uvicorn.org/) | Production ASGI server |
| [APScheduler](https://apscheduler.readthedocs.io/) | Background scheduler (used in standalone/in-container mode) |


## ⚙️ Architecture & How It Works

This project uses a **decoupled architecture** optimized for low memory usage and high reliability on free-tier container hosting:

```
┌─────────────────────────────────┐
│     GitHub Actions Runner       │
│  (Cron: every 30m / on-demand)  │
│                                 │
│  1. Camoufox launches browser   │
│  2. Solves Cloudflare Turnstile │
│  3. Intercepts KTU JSON payload │
│  4. Pre-fetches PDF attachments │
└────────────────┬────────────────┘
                 │
                 │ POST /api/sync (with X-Sync-Secret)
                 ▼
┌─────────────────────────────────┐
│       Render Web Service        │
│      (~38 MB RAM footprint)     │
│                                 │
│  • In-memory cache              │
│  • Instant response (< 20ms)    │
│  • Serves pre-cached PDFs       │
│  • Public REST endpoints        │
└─────────────────────────────────┘
```

1. **External Scraper via GitHub Actions**: Every 30 minutes, GitHub Actions runs Camoufox in a full-browser Linux environment. It solves KTU's Cloudflare Turnstile challenge and intercepts the raw API response and `x-token`.
2. **Attachment Pre-Caching**: While the Turnstile token is fresh, the workflow pre-downloads all PDF attachments, encodes them in base64, and POSTs the entire bundle to `/api/sync`.
3. **Ultra-Lightweight API Container**: Render runs a lightweight FastAPI app consuming only **~38 MB RAM** (well below Render's 512 MB limit) because the browser engine never runs inside the container.
4. **Instant PDF Downloads**: Calls to `/download/{encrypt_id}` are served directly from in-memory cache without hitting KTU or needing a live browser session.
5. **Secured On-Demand Refresh**: Calling `/refresh?secret=...` dispatches the GitHub Actions scraper workflow via GitHub API, guarded by secret authentication and a **mandatory 10-minute cooldown**.


## 📡 API Usage Examples

**Get all announcements:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements
```

**Get the 5 most recent announcements:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements?limit=5
```

**Filter by scheme (e.g., 2019 scheme + general circulars):**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements?scheme=2019
```

**Filter for new announcements only:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements?new_only=true
```

**Fetch a single announcement by ID:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements/1234
```

**Download an attached PDF:**
```bash
# -O and -J automatically save the file with its real filename
curl -O -J https://ktu-announcements-api-wxk8.onrender.com/download/{encrypt_id}
```

**Trigger on-demand scraper refresh:**
```bash
curl -H "Authorization: Bearer YOUR_SYNC_SECRET" \
  https://ktu-announcements-api-wxk8.onrender.com/refresh
```

**Check API health:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/health
```


## 🚀 Running Locally

### Option 1: Decoupled API Mode (Default, Recommended)

Runs the lightweight FastAPI service locally without launching a browser:

```bash
git clone https://github.com/ratherpixelate/ktu-announcements-api.git
cd ktu-announcements-api

# Install dependencies (using uv or pip)
uv sync
# or: pip install -r requirements.txt

# Run the API server (uses PORT env var, defaults to 8000)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

To populate data, run the scraper script locally:
```bash
RENDER_API_URL="http://localhost:8000" SYNC_SECRET="local_dev" uv run python scripts/sync_to_render.py
```

### Option 2: Standalone In-Container Mode (with Camoufox)

If you want the API container to run Camoufox internally using APScheduler:

```bash
# Set ENABLE_IN_CONTAINER_SCRAPER=true
ENABLE_IN_CONTAINER_SCRAPER=true uv run uvicorn app.main:app --port 8000
```

### Docker

```bash
# Build Docker image
docker build -t ktu-announcements-api .

# Run container (PORT can be overridden with -e PORT=8000)
docker run -p 8000:8000 -e PORT=8000 ktu-announcements-api
```


## 🔒 Environment Variables

| Variable | Description | Required For |
|---|---|---|
| `SYNC_SECRET` | Secret key used to authorize `/api/sync` and `/refresh` | Production deployment |
| `GITHUB_PAT` | GitHub Personal Access Token (`repo` scope) for workflow dispatch | On-demand `/refresh` |
| `GITHUB_REPO` | Target GitHub repository (e.g. `user/repo`) | On-demand `/refresh` |
| `RENDER_API_URL` | Render API URL where scraped data is POSTed | GitHub Actions scraper |
| `ENABLE_IN_CONTAINER_SCRAPER` | Set `true` to run Camoufox inside API container via APScheduler | Standalone local dev |
| `PORT` | Web server port (defaults to `8000`, Render sets `10000`) | Container config |


## 📝 License

This project is licensed under the [MIT License](./LICENSE).
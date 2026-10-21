# KTU Announcements API

An unofficial REST API for announcements published by [APJ Abdul Kalam Technological University (KTU)](https://ktu.edu.in). Built with FastAPI, Camoufox, and GitHub Actions.

> **Disclaimer:** This is an independent, community-maintained project and is not affiliated with, endorsed by, or connected to APJ Abdul Kalam Technological University.

## Live Service

- **Base URL:** [https://ktu-announcements-api-wxk8.onrender.com](https://ktu-announcements-api-wxk8.onrender.com)
- **Interactive Documentation:** [https://ktu-announcements-api-wxk8.onrender.com/docs](https://ktu-announcements-api-wxk8.onrender.com/docs)

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/announcements` | GET | List all cached announcements |
| `/announcements?limit=5` | GET | Limit response to the latest `N` records |
| `/announcements?new_only=true` | GET | Filter records flagged as new |
| `/announcements?scheme=2019` | GET | Filter records by scheme (`2015`, `2019`, `2024`, or `General`) |
| `/announcements/{id}` | GET | Retrieve a single announcement by ID |
| `/download/{encrypt_id}` | GET | Download an announcement attachment (pre-cached PDF) |
| `/health` | GET | Service status and cache timestamp |
| `/refresh` | GET | Dispatch on-demand scraper run (requires secret, 10m cooldown) |
| `/api/sync` | POST | Webhook for scraper data ingestion (requires `X-Sync-Secret`) |
| `/docs` | GET | OpenAPI / Swagger UI documentation |

## Architecture

The service uses a decoupled architecture to operate reliably within constrained container environments (such as Render's 512 MB free tier):

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
|   - Render web service (~38 MB RAM)   |
|   - In-memory data & PDF cache        |
|   - Sub-20ms response times           |
|   - Rate-limited /refresh endpoint    |
+---------------------------------------+
```

1. **Scraping**: GitHub Actions executes Camoufox in a headless environment every 30 minutes, completing the Turnstile verification and capturing KTU's announcements payload and auth token.
2. **Attachment Pre-caching**: While the Turnstile token is valid, the runner downloads all attached documents, encodes them in base64, and syncs the entire payload to the API server via `/api/sync`.
3. **API Serving**: The FastAPI application holds the latest announcements and attachments in memory, serving requests in milliseconds without executing a browser process or triggering remote calls on download.
4. **On-Demand Refresh**: The `/refresh` endpoint dispatches the GitHub Actions scraper workflow via the GitHub API. Access is protected by a shared secret and enforced by a mandatory 10-minute cooldown window.

## Usage Examples

Get all announcements:
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements
```

Filter by scheme:
```bash
curl "https://ktu-announcements-api-wxk8.onrender.com/announcements?scheme=2019"
```

Filter new announcements:
```bash
curl "https://ktu-announcements-api-wxk8.onrender.com/announcements?new_only=true"
```

Fetch a single announcement:
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements/1234
```

Download an attachment (saves with the original filename):
```bash
curl -O -J https://ktu-announcements-api-wxk8.onrender.com/download/{encrypt_id}
```

Trigger an on-demand refresh:
```bash
curl -H "Authorization: Bearer YOUR_SYNC_SECRET" \
  https://ktu-announcements-api-wxk8.onrender.com/refresh
```

Check service health:
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/health
```

## Local Development

### Option 1: Decoupled API Mode (Recommended)

Runs the FastAPI service without browser dependencies:

```bash
git clone https://github.com/ratherpixelate/ktu-announcements-api.git
cd ktu-announcements-api

# Install dependencies
uv sync
# or: pip install -r requirements.txt

# Start API server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

To populate the local cache, run the scraper script against localhost:
```bash
RENDER_API_URL="http://localhost:8000" SYNC_SECRET="local_dev" uv run python scripts/sync_to_render.py
```

### Option 2: Standalone Mode (In-Container Scraper)

Runs both the API and scheduled Camoufox scraping within the same process via APScheduler:

```bash
ENABLE_IN_CONTAINER_SCRAPER=true uv run uvicorn app.main:app --port 8000
```

### Docker

```bash
docker build -t ktu-announcements-api .
docker run -p 8000:8000 -e PORT=8000 ktu-announcements-api
```

## Environment Variables

| Variable | Description | Required For |
|---|---|---|
| `SYNC_SECRET` | Shared secret to authorize `/api/sync` and `/refresh` | Production deployment |
| `GITHUB_PAT` | GitHub Personal Access Token (`repo` scope) | On-demand `/refresh` dispatch |
| `GITHUB_REPO` | Target repository in `owner/repo` format | On-demand `/refresh` dispatch |
| `RENDER_API_URL` | Destination API URL for the sync payload | GitHub Actions scraper |
| `ENABLE_IN_CONTAINER_SCRAPER` | Enables internal APScheduler background scraping | Standalone mode |
| `PORT` | HTTP server port (defaults to `8000`) | Container deployment |

## License

This project is licensed under the [MIT License](./LICENSE).

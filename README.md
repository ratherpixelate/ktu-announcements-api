# KTU Announcements API

An unofficial REST API that scrapes and serves announcements from the [APJ Abdul Kalam Technological University (KTU)](https://ktu.edu.in) website. Built with **FastAPI**, **Playwright** (to bypass reCAPTCHA), and **APScheduler** for scheduled in-memory caching.

> ⚠️ This is an unofficial, community-maintained project and is **not affiliated with APJ Abdul Kalam Technological University**.


## 🌐 Live API

The API is publicly hosted and ready to use:

**Base URL:** [https://ktu-announcements-api-wxk8.onrender.com](https://ktu-announcements-api-wxk8.onrender.com)

| Endpoint | Description |
|---|---|
| `GET /announcements` | Returns all cached announcements |
| `GET /announcements?limit=5` | Returns the N most recent announcements |
| `GET /download/{encrypt_id}` | Downloads an attached document directly as a PDF |
| `GET /health` | API status and cache info |
| `GET /docs` | Interactive Swagger UI documentation |


## 🛠️ Tech Stack

| Tool | Purpose |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | Web framework & API routing |
| [Playwright](https://playwright.dev/python/) | Headless browser scraping (bypasses reCAPTCHA) |
| [httpx](https://www.python-httpx.org/) | High-speed async API requests & file downloading |
| [APScheduler](https://apscheduler.readthedocs.io/) | Scheduled background jobs for cache refresh |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | HTML parsing |
| [Uvicorn](https://www.uvicorn.org/) | ASGI server |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Environment variable management |



## 🚀 Running Locally

### Prerequisites

- Python 3.12+
- Docker (optional, recommended)

### Option 1: Run with Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/ratherpixelate/ktu-announcements-api.git
cd ktu-announcements-api

# Build the Docker image
docker build -t ktu-announcements-api .

# Run the container
docker run -p 8000:8000 ktu-announcements-api
```

The API will be available at `http://localhost:8000`.

### Option 2: Run without Docker

```bash
# Clone the repository
git clone https://github.com/ratherpixelate/ktu-announcements-api.git
cd ktu-announcements-api

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
playwright install-deps

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```


## 📡 API Usage Examples

**Get all announcements:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements
```

**Get the 5 most recent announcements:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/announcements?limit=5
```

**Download an attachment:**
```bash
# Use -O and -J to let curl automatically save the file with its original name
curl -O -J https://ktu-announcements-api-wxk8.onrender.com/download/{encrypt_id}
```

**Check API health and cache status:**
```bash
curl https://ktu-announcements-api-wxk8.onrender.com/health
```

## ⚙️ How It Works

1. On startup, the app uses **Playwright** to launch a headless Chromium browser and scrape announcements from the KTU website — bypassing reCAPTCHA in the process.
2. The scraped announcement data and the active authentication token are stored in a mutable **in-memory dictionary** to ensure thread-safe sharing between the background workers and FastAPI routes.
3. **APScheduler** runs a background job at regular intervals to refresh the cache automatically, keeping announcements up to date without manual intervention.
4. **FastAPI** exposes the cached data through clean REST endpoints with support for filtering via query parameters.


## 📝 License

This project is licensed under the [MIT License](./LICENSE).
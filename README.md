# KTU Announcements API

An unofficial REST API that scrapes and serves announcements from the APJ Abdul Kalam Technological University (KTU) website. 

Built with FastAPI, Playwright (to bypass reCAPTCHA), and APScheduler for in-memory caching.

## Live API
The API is publicly available at: **https://ktu-announcements-api-wxk8.onrender.com**

* `GET /announcements` - Returns all cached announcements
* `GET /announcements?limit=5` - Returns the 5 most recent announcements
* `GET /health` - API status and cache info
* `GET /docs` - Interactive Swagger UI documentation

## Disclaimer
This is an unofficial, community-maintained project and is not affiliated with APJ Abdul Kalam Technological University.
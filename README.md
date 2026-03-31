# monitoring-saas
![CI](https://github.com/mainlayer/monitoring-saas/actions/workflows/ci.yml/badge.svg) ![License](https://img.shields.io/badge/license-MIT-blue)

Uptime monitoring tool with Mainlayer subscription billing — like UptimeRobot, but built for AI agents and SaaS teams that need metered access control.

## Install

```bash
pip install mainlayer fastapi uvicorn httpx
```

## Quickstart

```python
import httpx

TOKEN = "your-mainlayer-token"
headers = {"Authorization": f"Bearer {TOKEN}"}

# Create a monitor
resp = httpx.post("http://localhost:8000/monitors", headers=headers, json={
    "name": "My API",
    "url": "https://api.example.com/health",
    "interval_seconds": 60,
})
monitor_id = resp.json()["id"]

# Check its status
status = httpx.get(f"http://localhost:8000/status/{monitor_id}", headers=headers).json()
print(status["status"], status["response_time_ms"], "ms")
```

## Features

- HTTP/TCP uptime monitoring with configurable check intervals
- Mainlayer subscription check on every API request (402 if not subscribed)
- On-demand status checks with 24-hour uptime percentage
- Multi-region support
- Async, production-ready FastAPI backend

## Run locally

```bash
MAINLAYER_API_KEY=... MAINLAYER_RESOURCE_ID=... uvicorn src.main:app --reload
```

📚 [mainlayer.fr](https://mainlayer.fr)

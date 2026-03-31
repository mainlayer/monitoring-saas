"""
Example: Create a monitor and poll its status.

Usage:
    MAINLAYER_TOKEN=<your-token> python examples/create_monitor.py
"""
import asyncio
import os
import httpx

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
TOKEN = os.getenv("MAINLAYER_TOKEN", "demo-token")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, headers=HEADERS) as client:
        # 1. Create a monitor
        resp = await client.post(
            "/monitors",
            json={
                "name": "Example.com",
                "url": "https://example.com",
                "monitor_type": "http",
                "interval_seconds": 60,
                "timeout_seconds": 10,
                "expected_status_code": 200,
                "regions": ["us-east-1"],
            },
        )
        resp.raise_for_status()
        monitor = resp.json()
        monitor_id = monitor["id"]
        print(f"Created monitor: {monitor_id} — {monitor['name']}")

        # 2. Get its current status
        resp = await client.get(f"/status/{monitor_id}")
        resp.raise_for_status()
        result = resp.json()
        print(f"Status: {result['status']} | Response time: {result['response_time_ms']:.1f}ms")
        print(f"Uptime (24h): {result['uptime_percentage_24h']}%")

        # 3. List all monitors
        resp = await client.get("/monitors")
        resp.raise_for_status()
        data = resp.json()
        print(f"\nTotal monitors: {data['total']}")
        for m in data["items"]:
            print(f"  - [{m['id'][:8]}] {m['name']} ({m['url']})")


if __name__ == "__main__":
    asyncio.run(main())

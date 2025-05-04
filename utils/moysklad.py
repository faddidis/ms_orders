import aiohttp
import os

MOYSKLAD_API_URL = "https://online.moysklad.ru/api/remap/1.2"
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN")

async def fetch_moysklad_orders():
    url = f"{MOYSKLAD_API_URL}/entity/customerorder?limit=50"
    headers = {"Authorization": f"Bearer {MOYSKLAD_TOKEN}"}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as resp:
            data = await resp.json()
            return data.get("rows", [])

async def update_moysklad_order_status(order_uuid: str, status_name: str):
    url = f"{MOYSKLAD_API_URL}/entity/customerorder/{order_uuid}"
    headers = {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "state": {
            "meta": {
                "href": f"{MOYSKLAD_API_URL}/entity/customerorder/metadata/states",
                "type": "state",
                "mediaType": "application/json",
                "name": status_name
            }
        }
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.put(url, json=payload) as resp:
            if resp.status >= 400:
                raise Exception(f"Failed to update MS order {order_uuid} to status {status_name}")

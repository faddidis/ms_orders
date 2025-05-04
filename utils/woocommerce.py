import aiohttp
import os

WC_API_URL = os.getenv("WC_API_URL")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET")

async def update_wc_order_status(order_id, status):
    url = f"{WC_API_URL}/orders/{order_id}"
    auth = aiohttp.BasicAuth(WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    payload = {"status": status}

    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.put(url, json=payload) as resp:
            if resp.status >= 400:
                raise Exception(f"Failed to update WooCommerce order {order_id}")
            return await resp.json()

async def get_wc_orders_for_status_sync():
    url = f"{WC_API_URL}/orders"
    auth = aiohttp.BasicAuth(WC_CONSUMER_KEY, WC_CONSUMER_SECRET)

    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.get(url) as resp:
            return await resp.json()

import aiohttp
import os
import httpx
import logging

WC_API_URL = os.getenv("WC_API_URL")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET")

async def update_wc_order_status(order_id, status):
    url = f"{WC_API_URL}/orders/{order_id}"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    payload = {"status": status}

    async with httpx.AsyncClient(auth=auth) as client:
        try:
            resp = await client.put(url, json=payload)
            resp.raise_for_status()
            logging.info(f"Updated WooCommerce order {order_id} status to '{status}'")
            return resp.json()
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error updating WC order {order_id} status: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to update WooCommerce order {order_id} status") from e
        except Exception as e:
            logging.exception(f"Error updating WC order {order_id} status: {e}")
            raise Exception(f"Failed to update WooCommerce order {order_id} status") from e

async def get_wc_orders_for_status_sync():
    url = f"{WC_API_URL}/orders?status=processing"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)

    async with httpx.AsyncClient(auth=auth) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error getting WC orders: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logging.exception(f"Error getting WC orders: {e}")
            return []

async def update_wc_order_number_and_uuid(order_id: int, moysklad_number: str, moysklad_uuid: str):
    """Обновляет номер заказа (name) и метаданные UUID МойСклад в WooCommerce."""
    url = f"{WC_API_URL}/orders/{order_id}"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    payload = {
        # "number": moysklad_number, # Обновление номера заказа WC может быть нежелательным
        "meta_data": [
            {"key": "_moysklad_uuid", "value": moysklad_uuid},
            {"key": "_moysklad_number", "value": moysklad_number} # Сохраняем номер МС в метаданные
        ]
    }

    async with httpx.AsyncClient(auth=auth) as client:
        try:
            resp = await client.put(url, json=payload)
            resp.raise_for_status()
            logging.info(f"WooCommerce order {order_id} metadata updated with Moysklad number {moysklad_number} and UUID {moysklad_uuid}")
            return resp.json()
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error updating WC order {order_id}: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to update WooCommerce order {order_id}") from e
        except Exception as e:
            logging.exception(f"Error updating WC order {order_id}: {e}")
            raise Exception(f"Failed to update WooCommerce order {order_id}") from e

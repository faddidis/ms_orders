import aiohttp
import httpx
import os
import logging

logger = logging.getLogger(__name__)

MOYSKLAD_API_URL = "https://online.moysklad.ru/api/remap/1.2"
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN")

async def fetch_moysklad_orders(params: dict | None = None):
    base_url = f"{MOYSKLAD_API_URL}/entity/customerorder"
    headers = {"Authorization": f"Bearer {MOYSKLAD_TOKEN}"}
    default_params = {"limit": 50}
    if params:
        default_params.update(params)

    async with httpx.AsyncClient(headers=headers) as client:
        try:
            resp = await client.get(base_url, params=default_params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("rows", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching MS orders: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.exception(f"Error fetching MS orders: {e}")
            return []

async def update_moysklad_order_status(order_uuid: str, status_name: str):
    url = f"{MOYSKLAD_API_URL}/entity/customerorder/{order_uuid}"
    headers = {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json"
    }

    status_href = await get_status_href_by_name(status_name)
    if not status_href:
        logger.error(f"Could not find href for Moysklad status: {status_name}")
        raise Exception(f"Status '{status_name}' not found in Moysklad metadata")

    payload = {
        "state": {
            "meta": {
                "href": status_href,
                "type": "state",
                "mediaType": "application/json"
            }
        }
    }

    async with httpx.AsyncClient(headers=headers) as client:
        try:
            resp = await client.put(url, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully updated MS order {order_uuid} status to {status_name}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error updating MS order {order_uuid} status: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to update MS order {order_uuid} status") from e
        except Exception as e:
            logger.exception(f"Error updating MS order {order_uuid} status: {e}")
            raise Exception(f"Failed to update MS order {order_uuid} status") from e

async def get_status_href_by_name(status_name: str) -> str | None:
    url = f"{MOYSKLAD_API_URL}/entity/customerorder/metadata"
    headers = {"Authorization": f"Bearer {MOYSKLAD_TOKEN}"}
    async with httpx.AsyncClient(headers=headers) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            metadata = resp.json()
            for state in metadata.get("states", []):
                if state.get("name") == status_name:
                    return state.get("meta", {}).get("href")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching MS metadata: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.exception(f"Error fetching MS metadata: {e}")
            return None

def validate_moysklad_response(response_json: dict | None) -> bool:
    try:
        if not isinstance(response_json, dict):
            logger.warning("Invalid Moysklad response: not a dict")
            return False
        if "id" not in response_json:
            logger.warning("Invalid Moysklad response: missing 'id'")
            return False
        if "meta" not in response_json or not isinstance(response_json.get("meta"), dict):
            logger.warning("Invalid Moysklad response: missing or invalid 'meta'")
            return False
        if "href" not in response_json["meta"]:
            logger.warning("Invalid Moysklad response: missing 'href' in 'meta'")
            return False
        return True
    except Exception as e:
        logger.exception(f"Error validating Moysklad response: {e}")
        return False

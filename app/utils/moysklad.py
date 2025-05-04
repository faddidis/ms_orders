import httpx
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

MOYSKLAD_API_URL = os.getenv("MOYSKLAD_API_URL", "https://online.moysklad.ru/api/remap/1.2")
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN")
HTTP_TIMEOUT = 15.0

# Кэш для метаданных статусов МойСклад (простая реализация)
_status_meta_cache: dict[str, str] = {}

async def _get_ms_auth_headers() -> dict[str, str]:
    if not MOYSKLAD_TOKEN:
        logger.error("MOYSKLAD_TOKEN is not set.")
        raise ValueError("Missing MOYSKLAD_TOKEN configuration.")
    return {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip"
    }

async def fetch_moysklad_orders(params: dict | None = None) -> list[dict]:
    """Получает заказы из МойСклад.
    (Требуется реальная реализация - определить нужные фильтры)
    """
    headers = await _get_ms_auth_headers()
    url = f"{MOYSKLAD_API_URL}/entity/customerorder"
    # Пример параметров: последние 10 измененных
    default_params = {'order': 'updated,desc', 'limit': 10}
    if params:
        default_params.update(params)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=default_params)
            response.raise_for_status()
            data = response.json()
            orders = data.get("rows", [])
            logger.info(f"Fetched {len(orders)} orders from Moysklad.")
            return orders
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching Moysklad orders: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.exception(f"Error fetching Moysklad orders: {e}")
        return []

async def get_moysklad_status_meta(status_name: str) -> str | None:
    """Получает метаданные статуса заказа МойСклад по имени (с кэшированием).
    (Требуется реальная реализация)
    """
    if status_name in _status_meta_cache:
        return _status_meta_cache[status_name]

    headers = await _get_ms_auth_headers()
    url = f"{MOYSKLAD_API_URL}/entity/customerorder/metadata"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            metadata = response.json()
            statuses = metadata.get("states", [])
            for state in statuses:
                if state.get("name") == status_name:
                    meta_href = state.get("meta", {}).get("href")
                    if meta_href:
                        _status_meta_cache[status_name] = meta_href # Кэшируем
                        logger.info(f"Fetched and cached meta for status '{status_name}'")
                        return meta_href
            logger.warning(f"Meta not found for Moysklad status '{status_name}'")
            return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching Moysklad metadata: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Error fetching Moysklad metadata: {e}")
        return None

async def update_moysklad_order_status(ms_uuid: str, ms_status_name: str):
    """Обновляет статус заказа в МойСклад.
    (Требуется реальная реализация)
    """
    status_meta_href = await get_moysklad_status_meta(ms_status_name)
    if not status_meta_href:
        logger.error(f"Cannot update Moysklad order {ms_uuid}: meta not found for status '{ms_status_name}'")
        return

    headers = await _get_ms_auth_headers()
    url = f"{MOYSKLAD_API_URL}/entity/customerorder/{ms_uuid}"
    payload = {
        "state": {
            "meta": {
                "href": status_meta_href,
                "type": "state",
                "mediaType": "application/json"
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.put(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"Successfully updated Moysklad order {ms_uuid} status to '{ms_status_name}'")
            # return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error updating Moysklad order {ms_uuid} status to '{ms_status_name}': {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        logger.exception(f"Error updating Moysklad order {ms_uuid} status: {e}")
        raise 
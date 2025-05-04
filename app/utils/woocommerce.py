import httpx
import os
import logging

logger = logging.getLogger(__name__)

WC_API_URL = os.getenv("WC_API_URL")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET")
HTTP_TIMEOUT = 15.0

async def update_wc_order_status(order_id: int, new_status: str):
    """Обновляет статус заказа в WooCommerce.
    (Требуется реальная реализация)
    """
    if not all([WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET]):
        logger.error("WC API credentials missing for status update.")
        raise ValueError("Missing WC API configuration.")

    url = f"{WC_API_URL}/orders/{order_id}"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    payload = {"status": new_status}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.put(url, json=payload, auth=auth)
            response.raise_for_status()
            logger.info(f"Successfully updated WC order {order_id} status to {new_status}")
            # В реальной реализации может потребоваться обработка ответа
            # return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error updating WC order {order_id} status to {new_status}: {e.response.status_code} - {e.response.text}")
        raise # Передаем исключение дальше
    except Exception as e:
        logger.exception(f"Error updating WC order {order_id} status: {e}")
        raise

async def get_wc_orders_for_status_sync(params: dict | None = None) -> list[dict]:
    """Получает заказы из WooCommerce для синхронизации статусов.
    (Требуется реальная реализация - определить критерии выборки)
    """
    if not all([WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET]):
        logger.error("WC API credentials missing for getting orders.")
        return []

    url = f"{WC_API_URL}/orders"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    # Пример параметров: получить последние 10 обновленных заказов
    default_params = {'orderby': 'modified', 'order': 'desc', 'per_page': 10}
    if params:
        default_params.update(params)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, params=default_params, auth=auth)
            response.raise_for_status()
            logger.info(f"Fetched {len(response.json())} orders from WC for status sync.")
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching WC orders: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.exception(f"Error fetching WC orders: {e}")
        return [] 
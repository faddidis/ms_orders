import json
import httpx
import os
import logging
import asyncio
from celery import Celery
from utils.woocommerce import update_wc_order_number_and_uuid
from app.db import get_connection, save_to_pending
from utils.moysklad import validate_moysklad_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MOYSKLAD_API_URL = os.getenv("MOYSKLAD_API_URL", "https://online.moysklad.ru/api/remap/1.2")
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/mydb")

WC_API_URL = os.getenv("WC_API_URL", "https://example.com/wp-json/wc/v3")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY", "ck_...")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET", "cs_...")

celery_app = Celery("worker", broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"))

# Основная задача синхронизации
@celery_app.task(name="process_order", bind=True, max_retries=3, default_retry_delay=60)
async def process_order(self, order_id: int, order_payload: dict):
    """Отправляет заказ в МойСклад и обновляет данные в WC."""
    headers = {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip" # Рекомендуется для API МойСклад
    }
    url = f"{MOYSKLAD_API_URL}/entity/customerorder"

    async with httpx.AsyncClient(headers=headers, timeout=20) as client:
        try:
            logger.info(f"[Task ID: {self.request.id}] Sending order {order_id} to Moysklad...")
            response = await client.post(url, json=order_payload)
            response.raise_for_status() # Проверка на HTTP ошибки
            data = response.json()

            if not validate_moysklad_response(data):
                error_msg = f"Invalid response from Moysklad for order {order_id}: {data}"
                logger.error(error_msg)
                # Не повторяем задачу при невалидном ответе, сохраняем в pending
                await save_to_pending(order_id, order_payload, "Invalid API response format")
                return # Выходим

            moysklad_uuid = data["id"]
            moysklad_number = data.get("name", "")

            # Обновляем WC асинхронно
            await update_wc_order_number_and_uuid(order_id, moysklad_number, moysklad_uuid)

            logger.info(f"[Task ID: {self.request.id}] Successfully synced order {order_id} (MS id: {moysklad_uuid}) with Moysklad")

            # Если заказ был в pending_sync, удаляем его
            async with get_connection() as conn:
                await conn.execute("DELETE FROM pending_sync WHERE order_id = $1", order_id)
                logger.info(f"[Task ID: {self.request.id}] Order {order_id} removed from pending_sync after successful sync.")

        except httpx.HTTPStatusError as exc:
            error_msg = f"HTTP error syncing order {order_id}: {exc.response.status_code} - {exc.response.text}"
            logger.error(error_msg)
            await save_to_pending(order_id, order_payload, error_msg)
            # Повторяем задачу при серверных ошибках (5xx) или таймаутах
            if 500 <= exc.response.status_code < 600 or isinstance(exc, httpx.TimeoutException):
                logger.warning(f"[Task ID: {self.request.id}] Retrying task for order {order_id} due to server error/timeout.")
                raise self.retry(exc=exc)
            # Не повторяем при клиентских ошибках (4xx)
        except Exception as e:
            error_msg = f"Failed to sync order {order_id}: {e}"
            logger.exception(error_msg)
            await save_to_pending(order_id, order_payload, str(e))
            # Можно добавить логику повтора для определенных не-HTTP исключений
            # raise self.retry(exc=e)

# Повторная попытка синхронизации отложенных заказов
@celery_app.task(name="retry_pending_orders", bind=True)
async def retry_pending_orders(self):
    """Выбирает заказы из pending_sync и ставит их в очередь process_order."""
    logger.info(f"[Task ID: {self.request.id}] Running retry_pending_orders task")
    try:
        async with get_connection() as conn:
            # Выбираем заказы, которые не обновлялись > 5 минут и имеют < 5 попыток
            rows = await conn.fetch("""
                SELECT id, order_id, order_payload, retry_count
                FROM pending_sync
                WHERE retry_count < 5 AND (last_attempt IS NULL OR last_attempt < NOW() - INTERVAL '5 minutes')
                ORDER BY created_at ASC
                LIMIT 20
            """)

            if not rows:
                logger.info(f"[Task ID: {self.request.id}] No pending orders to retry.")
                return

            logger.info(f"[Task ID: {self.request.id}] Found {len(rows)} orders to retry.")
            for row in rows:
                order_id = row["order_id"]
                order_payload = json.loads(row["order_payload"]) # Загружаем JSON
                retry_count = row["retry_count"]

                logger.info(f"[Task ID: {self.request.id}] Queuing retry for order {order_id} (Attempt: {retry_count + 1})")
                # Обновляем время попытки перед постановкой в очередь
                await conn.execute("UPDATE pending_sync SET last_attempt = now() WHERE id = $1", row["id"])
                # Ставим основную задачу в очередь
                process_order.delay(order_id, order_payload)
                # Не удаляем из pending_sync здесь, удаление происходит в process_order при успехе

    except Exception as e:
        logger.exception(f"[Task ID: {self.request.id}] Retry task failed: {e}")

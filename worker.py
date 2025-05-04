import json
import requests
import asyncpg
import os
import logging
from celery import Celery
from datetime import datetime, timedelta

from tasks.status_sync import sync_statuses_from_moysklad, sync_statuses_to_moysklad

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MOYSKLAD_API_URL = "https://online.moysklad.ru/api/remap/1.2"
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN", "your_token")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/mydb")

celery_app = Celery("worker", broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"))
celery_app.conf.beat_schedule = {
    'retry-pending-orders-every-5-minutes': {
        'task': 'retry_pending_orders',
        'schedule': 300.0,  # каждые 5 минут
    },
    'sync-statuses-from-ms-every-5-minutes': {
        'task': 'sync_statuses_from_moysklad',
        'schedule': 300.0,  # каждые 5 минут
    },
    'sync-statuses-to-ms-every-5-minutes': {
        'task': 'sync_statuses_to_moysklad',
        'schedule': 300.0,  # каждые 5 минут
    },
}


def validate_moysklad_response(response_json: dict) -> bool:
    try:
        if not isinstance(response_json, dict):
            return False
        required_keys = ["id", "meta"]
        for key in required_keys:
            if key not in response_json:
                return False
        if "href" not in response_json["meta"]:
            return False
        return True
    except Exception:
        return False


async def save_to_pending(order_id: int, payload: dict, error: str = ""):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO pending_sync (order_id, order_payload, error_message)
        VALUES ($1, $2, $3)
    """, order_id, json.dumps(payload), error)
    await conn.close()
    logger.info(f"Order {order_id} saved to pending_sync due to error")


@celery_app.task(name="process_order")
def process_order(order_id: int, order_payload: dict):
    import asyncio
    asyncio.run(_process_order(order_id, order_payload))


async def _process_order(order_id: int, order_payload: dict):
    try:
        headers = {
            "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
            "Content-Type": "application/json"
        }

        logger.info(f"Sending order {order_id} to Moysklad...")
        response = requests.post(
            f"{MOYSKLAD_API_URL}/entity/customerorder",
            json=order_payload,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        if not validate_moysklad_response(data):
            logger.error(f"Invalid response from Moysklad for order {order_id}: {data}")
            await save_to_pending(order_id, order_payload, "Invalid API response format")
            return

        # Здесь можно обновить номер и UUID в WooCommerce
        ms_uuid = data["id"]
        from utils.woocommerce import update_wc_order_number_and_uuid
        await update_wc_order_number_and_uuid(order_id, data["name"], ms_uuid)

        logger.info(f"Successfully synced order {order_id} with Moysklad")

    except Exception as e:
        logger.exception(f"Failed to sync order {order_id}: {e}")
        await save_to_pending(order_id, order_payload, str(e))


@celery_app.task(name="retry_pending_orders")
def retry_pending_orders():
    import asyncio
    asyncio.run(_retry_pending_orders())


async def _retry_pending_orders():
    logger.info("Running retry_pending_orders task")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, order_id, order_payload, retry_count
            FROM pending_sync
            ORDER BY created_at ASC
            LIMIT 20
        """)

        for row in rows:
            try:
                await _process_order(row["order_id"], row["order_payload"])
                await conn.execute("DELETE FROM pending_sync WHERE id = $1", row["id"])
                logger.info(f"Order {row['order_id']} retried and removed from pending_sync")
            except Exception as e:
                await conn.execute("""
                    UPDATE pending_sync
                    SET retry_count = retry_count + 1,
                        last_attempt = now(),
                        error_message = $1
                    WHERE id = $2
                """, str(e), row["id"])
                logger.error(f"Retry failed for order {row['order_id']}: {e}")

        await conn.close()
    except Exception as e:
        logger.exception(f"Retry task failed: {e}")


@celery_app.task(name="sync_statuses_from_moysklad")
def sync_statuses_from_moysklad_task():
    import asyncio
    asyncio.run(sync_statuses_from_moysklad())


@celery_app.task(name="sync_statuses_to_moysklad")
def sync_statuses_to_moysklad_task():
    import asyncio
    asyncio.run(sync_statuses_to_moysklad())

# tasks/status_sync.py

import asyncpg
import os
import logging
from app.db import get_connection
from utils.woocommerce import update_wc_order_status, get_wc_orders_for_status_sync
from utils.moysklad import fetch_moysklad_orders, update_moysklad_order_status

# Импортируем celery_app
from app.worker import celery_app

logger = logging.getLogger(__name__)

async def get_status_mapping():
    """Загружает маппинг статусов из базы данных."""
    # Используем `async with` для управления соединением
    async with get_connection() as conn:
        try:
            rows = await conn.fetch("SELECT moysklad_status, woocommerce_status, ms_status_meta FROM status_mapping")
            # Создаем два словаря для удобного поиска
            ms_to_wc = {row["moysklad_status"]: row["woocommerce_status"] for row in rows if row["moysklad_status"]}
            wc_to_ms = {row["woocommerce_status"]: row["moysklad_status"] for row in rows if row["woocommerce_status"]}
            # Добавляем meta для статусов МойСклад, если они есть
            ms_meta = {row["moysklad_status"]: row["ms_status_meta"] for row in rows if row["ms_status_meta"]}
            return {
                "ms_to_wc": ms_to_wc,
                "wc_to_ms": wc_to_ms,
                "ms_meta": ms_meta # Добавляем метаданные статусов МС
            }
        except Exception as e:
            logger.exception(f"Error fetching status mapping: {e}")
            return {"ms_to_wc": {}, "wc_to_ms": {}, "ms_meta": {}}

@celery_app.task(name="sync_statuses_from_moysklad_task")
async def sync_statuses_from_moysklad_task():
    """Celery задача: Синхронизирует статусы из МойСклад в WooCommerce."""
    logger.info("Starting sync statuses from Moysklad to WooCommerce...")
    mapping = await get_status_mapping()
    ms_to_wc = mapping["ms_to_wc"]
    if not ms_to_wc:
        logger.warning("Moysklad to WC status mapping is empty. Skipping sync.")
        return

    # Получаем недавно измененные заказы из МойСклад
    # Можно добавить фильтр по времени (`updatedFrom`)
    orders = await fetch_moysklad_orders(params={"expand": "state"}) # Расширяем state для получения имени статуса

    updated_count = 0
    for order in orders:
        wc_order_id = order.get("externalCode") # Предполагаем, что ID WC хранится здесь
        ms_status_name = order.get("state", {}).get("name")
        ms_order_uuid = order.get("id")

        if wc_order_id and ms_status_name and ms_status_name in ms_to_wc:
            new_wc_status = ms_to_wc[ms_status_name]
            try:
                # Тут нужна проверка текущего статуса в WC, чтобы не обновлять зря
                # current_wc_order = await get_wc_order_details(wc_order_id) # Нужна такая функция
                # if current_wc_order and current_wc_order['status'] != new_wc_status:
                logger.info(f"Updating WC order {wc_order_id} to status '{new_wc_status}' from MS status '{ms_status_name}' (MS id: {ms_order_uuid})")
                await update_wc_order_status(wc_order_id, new_wc_status)
                updated_count += 1
                # else:
                #     logger.debug(f"Skipping WC order {wc_order_id}, status '{new_wc_status}' already set.")
            except Exception as e:
                logger.error(f"Failed to update WC order {wc_order_id} from MS order {ms_order_uuid}: {e}")
        elif wc_order_id and ms_status_name:
            logger.debug(f"Skipping WC order {wc_order_id} (MS id: {ms_order_uuid}): MS Status '{ms_status_name}' not in mapping.")

    logger.info(f"Finished sync statuses from Moysklad to WooCommerce. Updated {updated_count} orders.")

@celery_app.task(name="sync_statuses_to_moysklad_task")
async def sync_statuses_to_moysklad_task():
    """Celery задача: Синхронизирует статусы из WooCommerce в МойСклад."""
    logger.info("Starting sync statuses from WooCommerce to Moysklad...")
    mapping = await get_status_mapping()
    wc_to_ms = mapping["wc_to_ms"]
    if not wc_to_ms:
        logger.warning("WooCommerce to Moysklad status mapping is empty. Skipping sync.")
        return

    # Получаем заказы из WC (например, только те, что изменились недавно или определенные статусы)
    orders = await get_wc_orders_for_status_sync() # Эта функция должна возвращать и метаданные

    updated_count = 0
    for order in orders:
        wc_id = order["id"]
        wc_status = order["status"]
        # Ищем UUID МойСклад в метаданных
        ms_uuid = None
        for meta in order.get("meta_data", []):
            if meta.get("key") == "_moysklad_uuid":
                ms_uuid = meta.get("value")
                break

        if ms_uuid and wc_status and wc_status in wc_to_ms:
            new_ms_status_name = wc_to_ms[wc_status]
            try:
                # Тут нужна проверка текущего статуса в МС
                # current_ms_order = await fetch_moysklad_order_details(ms_uuid) # Нужна такая функция
                # if current_ms_order and current_ms_order['state']['name'] != new_ms_status_name:
                logger.info(f"Updating MS order {ms_uuid} to status '{new_ms_status_name}' from WC order {wc_id} (WC status: '{wc_status}')")
                await update_moysklad_order_status(ms_uuid, new_ms_status_name)
                updated_count += 1
                # else:
                #      logger.debug(f"Skipping MS order {ms_uuid}, status '{new_ms_status_name}' already set.")
            except Exception as e:
                logger.error(f"Failed to update MS order {ms_uuid} from WC order {wc_id}: {e}")
        elif ms_uuid and wc_status:
             logger.debug(f"Skipping MS order {ms_uuid} (WC id: {wc_id}): WC Status '{wc_status}' not in mapping.")

    logger.info(f"Finished sync statuses from WooCommerce to Moysklad. Updated {updated_count} orders.")

# Старые функции sync_statuses_from_moysklad и sync_statuses_to_moysklad заменены задачами Celery

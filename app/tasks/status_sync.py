# tasks/status_sync.py

import asyncpg
import os
import logging
from app.db import get_connection
from app.worker import celery_app # Импортируем Celery app
# Импортируем функции из utils
from app.utils.woocommerce import update_wc_order_status, get_wc_orders_for_status_sync
from app.utils.moysklad import fetch_moysklad_orders, update_moysklad_order_status

logger = logging.getLogger(__name__)

async def get_status_mapping():
    """Загружает маппинг статусов из БД."""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("SELECT moysklad_status, woocommerce_status FROM status_mapping")
            ms_to_wc = {row["moysklad_status"]: row["woocommerce_status"] for row in rows}
            wc_to_ms = {v: k for k, v in ms_to_wc.items()} # Генерируем обратный маппинг
            return {
                "ms_to_wc": ms_to_wc,
                "wc_to_ms": wc_to_ms
            }
    except Exception as e:
        logger.exception("Failed to get status mapping from DB")
        return None # Возвращаем None при ошибке

@celery_app.task(name="sync_statuses_from_moysklad_task")
async def sync_statuses_from_moysklad():
    """Задача Celery: Синхронизирует статусы ИЗ МойСклад В WooCommerce."""
    logger.info("Starting sync_statuses_from_moysklad task...")
    mapping_data = await get_status_mapping()
    if not mapping_data:
        logger.error("Cannot sync statuses from Moysklad: status mapping unavailable.")
        return

    ms_to_wc = mapping_data["ms_to_wc"]
    # Получаем заказы из МС (можно добавить фильтры)
    ms_orders = await fetch_moysklad_orders(params={'expand': 'state'}) # Расширяем, чтобы получить объект статуса

    updated_count = 0
    for order in ms_orders:
        # externalCode должен содержать ID заказа WC
        wc_order_id_str = order.get("externalCode")
        ms_status_obj = order.get("state")
        ms_status_name = ms_status_obj.get("name") if ms_status_obj else None
        ms_uuid = order.get("id")

        if not wc_order_id_str or not ms_status_name:
            # logger.debug(f"Skipping MS order {ms_uuid}: missing externalCode or state name.")
            continue

        try:
            wc_order_id = int(wc_order_id_str)
        except ValueError:
            logger.warning(f"Invalid externalCode '{wc_order_id_str}' for MS order {ms_uuid}. Skipping.")
            continue

        if ms_status_name in ms_to_wc:
            target_wc_status = ms_to_wc[ms_status_name]
            # TODO: Добавить проверку текущего статуса в WC, чтобы не обновлять без надобности
            try:
                logger.info(f"Updating WC order {wc_order_id} to status '{target_wc_status}' from MS status '{ms_status_name}'")
                await update_wc_order_status(wc_order_id, target_wc_status)
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update WC order {wc_order_id} status: {e}")
                # Можно добавить логику ретраев или сохранения в очередь ошибок
        # else:
            # logger.debug(f"No mapping found for MS status '{ms_status_name}'")

    logger.info(f"Finished sync_statuses_from_moysklad task. Updated {updated_count} WC orders.")


@celery_app.task(name="sync_statuses_to_moysklad_task")
async def sync_statuses_to_moysklad():
    """Задача Celery: Синхронизирует статусы ИЗ WooCommerce В МойСклад."""
    logger.info("Starting sync_statuses_to_moysklad task...")
    mapping_data = await get_status_mapping()
    if not mapping_data:
        logger.error("Cannot sync statuses to Moysklad: status mapping unavailable.")
        return

    wc_to_ms = mapping_data["wc_to_ms"]
    # Получаем заказы из WC для синхронизации (можно добавить фильтры)
    wc_orders = await get_wc_orders_for_status_sync() # Пример: последние измененные

    updated_count = 0
    for order in wc_orders:
        wc_id = order.get("id")
        wc_status = order.get("status")
        # Ищем UUID МойСклад в метаданных
        ms_uuid = None
        for meta in order.get("meta_data", []):
            if meta.get("key") == "_moysklad_uuid":
                ms_uuid = meta.get("value")
                break

        if not ms_uuid or not wc_status:
            # logger.debug(f"Skipping WC order {wc_id}: missing moysklad_uuid or status.")
            continue

        if wc_status in wc_to_ms:
            target_ms_status_name = wc_to_ms[wc_status]
            # TODO: Добавить проверку текущего статуса в МС, чтобы не обновлять без надобности
            try:
                logger.info(f"Updating MS order {ms_uuid} to status '{target_ms_status_name}' from WC order {wc_id} (status: '{wc_status}')")
                await update_moysklad_order_status(ms_uuid, target_ms_status_name)
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update MS order {ms_uuid} status: {e}")
                # Можно добавить логику ретраев или сохранения в очередь ошибок
        # else:
            # logger.debug(f"No mapping found for WC status '{wc_status}'")

    logger.info(f"Finished sync_statuses_to_moysklad task. Updated {updated_count} Moysklad orders.") 
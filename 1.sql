CREATE TABLE pending_sync (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    order_payload JSONB NOT NULL,
    retry_count INTEGER DEFAULT 0,
    last_attempt TIMESTAMP DEFAULT now(),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE status_mapping (
    id SERIAL PRIMARY KEY,
    moysklad_status TEXT NOT NULL,
    woocommerce_status TEXT NOT NULL,
    UNIQUE (moysklad_status)
);


-- migrations/001_create_status_mapping.sql

-- Примеры соответствий (можно кастомизировать)
INSERT INTO status_mapping (moysklad_status, woocommerce_status)
VALUES 
    ('Выполнен', 'completed'),
    ('Отложен', 'on-hold'),
    ('Новый', 'processing'),
    ('Отменен', 'cancelled'),
    ('Подтверждён', 'on-hold')
ON CONFLICT DO NOTHING;

-- Таблица для "мертвых" заказов, которые не удалось обработать
CREATE TABLE dead_letter_sync (
    id SERIAL PRIMARY KEY,
    original_pending_id INTEGER, -- Опционально: ID из исходной таблицы pending_sync
    order_id INTEGER NOT NULL,
    order_payload JSONB NOT NULL,
    final_error_message TEXT,
    failed_at TIMESTAMP DEFAULT now()
);

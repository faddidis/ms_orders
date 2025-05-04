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

CREATE TABLE IF NOT EXISTS status_mapping (
    id SERIAL PRIMARY KEY,
    moysklad_status TEXT NOT NULL UNIQUE,
    woocommerce_status TEXT NOT NULL
);

-- Примеры соответствий (можно кастомизировать)
INSERT INTO status_mapping (moysklad_status, woocommerce_status)
VALUES 
    ('Выполнен', 'completed'),
    ('Отложен', 'on-hold'),
    ('Новый', 'processing'),
    ('Отменен', 'cancelled'),
    ('Подтверждён', 'on-hold')
ON CONFLICT DO NOTHING;

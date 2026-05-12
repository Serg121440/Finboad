# Finboard — Финансовая аналитика маркетплейсов

Streamlit-дашборд для анализа продаж на Wildberries и Ozon с интеграцией Google Sheets.

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка переменных окружения

```bash
cp .env.example .env
```

Заполните `.env`:

| Переменная | Описание |
|---|---|
| `WB_API_TOKEN` | Токен Wildberries Statistics API |
| `OZON_CLIENT_ID` | Client-Id аккаунта продавца Ozon |
| `OZON_API_KEY` | API-ключ Ozon Seller API |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | Путь к JSON-файлу сервисного аккаунта Google |
| `GOOGLE_SPREADSHEET_ID` | ID Google Таблицы |
| `DATABASE_URL` | (опционально) PostgreSQL URL; по умолчанию — SQLite |

### 3. Google Sheets (только чтение)

1. Создайте сервисный аккаунт в Google Cloud Console.
2. Включите Google Sheets API и Google Drive API.
3. Скачайте JSON-ключ и сохраните как `credentials.json`.
4. Выдайте сервисному аккаунту доступ к таблице (роль «Читатель»).

### 4. Запуск дашборда

```bash
streamlit run dashboard/app.py
```

Откроется браузер на `http://localhost:8501`.

### 5. Запуск планировщика (фоново)

```bash
python scheduler.py
```

Планировщик выполняет полный синхрон при старте, затем ежедневно в 06:00 МСК.

## Структура проекта

```
Finboard/
├── connectors/
│   ├── wb_connector.py             # Wildberries Statistics API
│   ├── ozon_connector.py           # Ozon Seller API
│   └── google_sheets_connector.py  # Google Sheets (read-only)
├── analytics/
│   └── metrics.py                  # Расчёт финансовых метрик
├── database/
│   └── db.py                       # SQLAlchemy + SQLite/PostgreSQL
├── dashboard/
│   └── app.py                      # Streamlit-дашборд
├── normalizer.py                   # Нормализация данных из всех источников
├── scheduler.py                    # APScheduler (06:00 МСК)
├── config.py                       # Конфигурация из .env
├── requirements.txt
└── .env.example
```

## Метрики дашборда

- **KPI**: выручка брутто/нетто, чистая прибыль, маржинальность, доля возвратов
- **Динамика**: выручка и прибыль по дням с разбивкой по маркетплейсу
- **Сравнение WB vs Ozon**: маржинальность, выручка, структура затрат
- **Топ-20 SKU**: по чистой прибыли с полными метриками
- **Структура затрат**: комиссия / логистика / возвраты / прибыль (pie chart)
- **ABC-анализ**: классификация SKU по вкладу в прибыль

## Фильтры

- Период (диапазон дат)
- Маркетплейс (WB, Ozon, или все)
- Категория товара

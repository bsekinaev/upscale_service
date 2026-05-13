# Upscale Service – асинхронное увеличение изображений через ИИ

Сервис на **Flask + Celery + Redis**, который принимает изображение, обрабатывает его нейросетью EDSR и отдаёт
увеличенный в 2 раза результат без сохранения на диск.

[![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)](https://docs.celeryq.dev)
[![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io)
[![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)](https://opencv.org)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)

---

## ✨ Что умеет

- Асинхронный апскейлинг: загрузил картинку → получил `task_id` → скачал результат.
- Нейросеть EDSR (2x) загружается **один раз** и не перечитывается с диска.
- Файлы не сохраняются на диск – всё через Redis (TTL 1 час).
- Три эндпоинта: `POST /upscale`, `GET /tasks/<id>`, `GET /processed/<id>`.
- Докеризовано (Flask, Celery, Redis в одном `docker-compose.yml`).
- Покрыто тестами.

---

## 🚀 Быстрый старт

1. Убедись, что Docker установлен.
2. Клонируй репозиторий:
   ```bash
   git clone https://github.com/bsekinaev/upscale-service.git
   cd upscale-service
   ```
   Модель `EDSR_x2.pb` уже лежит в корне.
3. Запусти:
   ```bash
   docker-compose up --build -d
   ```
4. Сервис готов к работе на `http://localhost:5000`.

### Пример использования

```bash
# Загрузка изображения
curl -X POST -F "file=@input.jpg" http://localhost:5000/upscale
# → {"task_id":"..."}

# Проверка статуса
curl http://localhost:5000/tasks/<task_id>
# → {"status":"SUCCESS","download_url":"/processed/..."}

# Скачать результат
curl http://localhost:5000/processed/<task_id> -o upscaled.png
```

---

## 📡 API Endpoints

| Метод | Путь                   | Описание                                          | Ответ                                                                   |
|-------|------------------------|---------------------------------------------------|-------------------------------------------------------------------------|
| POST  | `/upscale`             | Загрузить файл (multipart/form-data, поле `file`) | `{"task_id":"uuid"}` (202)                                              |
| GET   | `/tasks/<task_id>`     | Проверить статус задачи                           | `{"status":"PENDING"}` или `{"status":"SUCCESS", "download_url":"..."}` |
| GET   | `/processed/<task_id>` | Скачать обработанный PNG                          | Файл `task_id.png`                                                      |

Поддерживаются форматы: PNG, JPEG, BMP, TIFF.

---

## 🧪 Тесты

```bash
docker-compose exec flask pytest tests/
```

Тесты проверяют:

- Отказ при отсутствии файла.
- Полный цикл: загрузка → обработка → получение статуса `SUCCESS` и файла.

Celery в тестах работает синхронно (`task_always_eager`, `task_store_eager_result`).

---
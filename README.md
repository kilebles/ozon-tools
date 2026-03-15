# Ozon Positions Parser

Парсит позиции товаров в поиске Ozon и записывает результаты в Google Sheets.

## Файлы конфигурации

- `cookies.json` — куки из браузера для авторизации на seller.ozon.ru
- `credentials.json` — Google service account для доступа к Sheets
- `proxy.txt` — прокси в формате `host:port:user:password`
- `.env` — переменные окружения (SPREADSHEET_ID, COMPANY_ID и др.)

## Установка на сервер (Ubuntu/Debian)

```bash
apt-get install -y xvfb
playwright install-deps chromium
playwright install chromium
```

## Запуск вручную

```bash
cd /opt/ozon-tools
xvfb-run --server-args="-screen 0 1920x1080x24" uv run src/main.py
```

## Настройка автозапуска через systemd (каждый час)

```bash
# Скопировать юниты
cp /opt/ozon-tools/ozon-positions.service /etc/systemd/system/
cp /opt/ozon-tools/ozon-positions.timer /etc/systemd/system/

# Активировать
systemctl daemon-reload
systemctl enable --now ozon-positions.timer

# Запустить вручную для теста
systemctl start ozon-positions.service
```

## Запуск бота

```bash
cp /opt/ozon-tools/ozon-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ozon-bot.service
```

## Управление

```bash
# Статус таймера и время следующего запуска
systemctl list-timers ozon-positions.timer

# Статус сервиса
systemctl status ozon-positions.service

# Логи в реальном времени
journalctl -u ozon-positions.service -f

# Логи за последний запуск
journalctl -u ozon-positions.service -n 100

# Остановить таймер
systemctl stop ozon-positions.timer

# Отключить автозапуск
systemctl disable ozon-positions.timer

# Логи бота
journalctl -u ozon-bot.service -f

# Перезапустить бота
systemctl restart ozon-bot.service
```

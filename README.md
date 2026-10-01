<div align="right">
  <a href="README_EN.md">English</a>
</div>

# Remnawave Panel Monitoring

Автономный стек Prometheus + Grafana для хоста Remnawave-панели. Подключается к существующей docker-сети панели, скрейпит её нативный эндпоинт метрик и разворачивает дашборд 25064. Не зависит от центрального стека мониторинга.

---

## <img src="assets/icons/share-08.svg" width="24" alt="" /> Архитектура

```
Remnawave-панель
  remnawave:3001/metrics  (HTTP basic auth)
        |
        | docker-сеть: remnawave-network
        v
  monitoring-prometheus   (127.0.0.1:9090, хранение 15d, 512M)
        |
        v
  monitoring-grafana      (127.0.0.1:3002, 256M)
        |
        | SSH-туннель: рабочая машина 3001 -> хост 3002
        v
  браузер @ localhost:3001
```

Всё слушает `127.0.0.1` на хосте панели. Доступ с рабочей машины — через SSH-туннель к хосту панели (алиас из `PANEL_HOST`). Порт 3001 на хосте занят эндпоинтом метрик панели, поэтому Grafana публикуется на 3002; туннель отображает порт `3001` рабочей машины на `3002` хоста.

---

## <img src="assets/icons/folder-01.svg" width="24" alt="" /> Структура

```
.
├── docker-compose.yml                              # prometheus + grafana; подключается к внешней remnawave-network
├── .env                                            # GF_SECURITY_ADMIN_PASSWORD, PANEL_HOST (в .gitignore)
├── .env.example                                    # шаблон
├── setup.sh                                        # интерактивный визард установки (ключ + туннель + деплой)
├── deploy.sh                                       # синхронизация конфигов, рендер кредов на хосте, docker compose up -d
├── Makefile                                        # ops-команды
├── prometheus/
│   ├── prometheus.yml.tmpl                         # шаблон скрейпа; рендерится в prometheus.yml на хосте (username подставляется)
│   └── alerts.yml                                  # правила алертов
├── alertmanager/
│   ├── alertmanager.yml                            # роутинг: notify=telegram -> webhook в monitoring-tg-relay
│   └── tg_relay.py                                 # webhook -> Telegram rich message (вёрстка бота панели); chat/thread/токен рендерятся на хосте
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── prometheus.yml                      # источник данных Prometheus (uid=prometheus, по умолчанию)
│   │   └── dashboards/
│   │       └── provider.yml                        # file-провайдер -> /var/lib/grafana/dashboards
│   └── dashboards/
│       └── remnawave-25064.json                    # дашборд
└── assets/
    └── icons/                                      # завендоренные иконки Hugeicons (для этого README)
```

---

## <img src="assets/icons/rocket-01.svg" width="24" alt="" /> Развёртывание

**Быстрый старт.** Интерактивный визард прокинет ваш SSH-ключ в панель (`ssh-copy-id`), пропишет alias с туннелем в `~/.ssh/config`, проверит панель, сгенерит пароль Grafana и задеплоит:

```bash
./setup.sh
```

Дальше — `ssh <alias>` → `http://localhost:3001`.

### Ручная установка

**Требования**

- SSH-алиас вашей панели в `~/.ssh/config` с проброской портов (см. раздел «Доступ»); имя алиаса задаётся в `PANEL_HOST`
- работающая Remnawave-панель с включёнными метриками
- docker-сеть `remnawave-network` на хосте

**Шаги**

```bash
cp .env.example .env
# задать GF_SECURITY_ADMIN_PASSWORD (openssl rand -hex 16) и PANEL_HOST
./deploy.sh
# или указать другой хост: ./deploy.sh other-alias
```

`deploy.sh` читает `METRICS_USER` и `METRICS_PASS` из `/opt/remnawave/.env` на хосте панели, рендерит `prometheus.yml` (username) и `prometheus/metrics_pass` (пароль, с chown на `65534:65534`, так как Prometheus работает под `nobody`), затем выполняет `docker compose up -d` и перезагружает Prometheus. Учётные данные панели в этом репозитории не хранятся.

**Команды Make**

| Команда | Действие |
|---|---|
| `make deploy` | запуск deploy.sh для HOST |
| `make ps` | docker compose ps |
| `make logs` | docker compose logs -f |
| `make down` | docker compose down |
| `make targets` | статус скрейп-целей Prometheus |

Переопределить хост: `HOST=...`, например `make deploy HOST=other-alias`.

**Несколько панелей.** Создайте `.env.<host>` (например `.env.ranetka-panel`) со своим `GF_SECURITY_ADMIN_PASSWORD`, затем `./deploy.sh <host>` — он подхватит этот файл вместо `.env`. Метрики каждой панели читаются с её собственного хоста.

---

## <img src="assets/icons/key-01.svg" width="24" alt="" /> Доступ

Пробросьте порты до хоста панели в `~/.ssh/config` (`PANEL_HOST` — имя этого алиаса):

```
Host remnawave-panel
  HostName <ip-панели>
  User root
  LocalForward 3001 127.0.0.1:3002   # Grafana (на хосте слушает 3002)
  LocalForward 9090 127.0.0.1:9090   # Prometheus
```

Затем `ssh remnawave-panel` и откройте:

| URL | Что |
|---|---|
| `http://localhost:3001` | Grafana (логин: `admin` / `GF_SECURITY_ADMIN_PASSWORD`) |
| `http://localhost:9090` | Prometheus |

Порты `3001` и `9090` рабочей машины общие с другими туннель-хостами. Держите открытым один туннель за раз.

---

## <img src="assets/icons/chart-line-data-01.svg" width="24" alt="" /> Алерты

Заданы в `prometheus/alerts.yml`. Вычисляются Prometheus и уходят в `monitoring-alertmanager`. В Telegram доставляются только алерты с лейблом `notify: telegram`: Alertmanager шлёт их вебхуком в `monitoring-tg-relay` (`alertmanager/tg_relay.py`), а тот публикует rich message (`sendRichMessage`) в вёрстке бота панели: `эмодзи #тег`, заголовок, разделитель, строки `Key: value`. Если Telegram не примет rich message, уходит то же самое обычным HTML. Поля карточки задаются аннотациями правила: `emoji`, `tag`, `title`, `name`, `reason`, `provider`, `address`; `Last status change` берётся из `startsAt` (UTC). Чат и топик берутся из `TELEGRAM_NOTIFY_NODES` (`chat_id[:thread_id]`), токен из `TELEGRAM_BOT_TOKEN` в `/opt/remnawave/.env` панели. Проверить вёрстку без отправки: `python3 alertmanager/tg_relay.py --render < webhook.json`. Остальные алерты видны только в UI Prometheus/Alertmanager: о падении нод панель уведомляет сама.

| Алерт | Выражение | For | Telegram |
|---|---|---|---|
| `RemnawavePanelMetricsDown` | `up{job="remnawave"} == 0` | 2m | нет |
| `RemnawaveNodeDown` | `remnawave_node_status * on(node_uuid) group_left(node_name) remnawave_node_basic_info == 0` | 3m | нет |
| `RemnawaveAllNodesDown` | `sum(remnawave_node_status) == 0` | 2m | нет |
| `NodeOnlineCollapsed` | среднее `remnawave_node_online_users` за 15m < 0.5 × то же сутки назад, при вчерашнем ≥ 15 | 20m | да |

`NodeOnlineCollapsed` ловит сгорание IP ноды. На истории за 15 дней он сработал на всех известных блокировках (21–23.09, 28.09). Он же срабатывает на плановый перенос юзеров. После события алерт держится до ~24 ч, пока не уйдёт вчерашняя база, поэтому сообщение приходит один раз (`repeat_interval: 24h`, без resolved). Заглушить ноду на время переезда:

```bash
docker exec monitoring-alertmanager amtool --alertmanager.url=http://localhost:9093 \
  silence add alertname=NodeOnlineCollapsed node_name=de-001 --duration=26h --comment="переезд"
```

**Имена нод.** В Remnawave v2.7.0+ лейблы `node_name` и страны вынесены в `remnawave_node_basic_info` для снижения кардинальности. Чтобы получить читаемые имена в любом запросе, соединяйте по `node_uuid`:

```promql
remnawave_node_online_users * on(node_uuid) group_left(node_name) remnawave_node_basic_info
```

---

## <img src="assets/icons/help-circle.svg" width="24" alt="" /> Почему этого нет в самой Remnawave

Remnawave отдаёт эндпоинт метрик и публикует дашборд 25064, но намеренно не поставляет стек Prometheus/Grafana. Три причины:

1. **Кардинальность.** История по пользователям должна жить в PostgreSQL, а не в time-series-хранилище Prometheus.
2. **Безопасность и изоляция.** Метрики нод агрегируются панелью, а не выставляются наружу с каждой ноды.
3. **Разделение ответственности.** Prometheus отвечает только за здоровье и алерты. Лимиты трафика и блокировки остаются в бэкенде панели.

Этот репозиторий — операторская обвязка, связывающая эти части.

---

## <img src="assets/icons/server-stack-01.svg" width="24" alt="" /> Смежное и на будущее

| Инструмент | Назначение | Брать? |
|---|---|---|
| [hteppl/remnawave-prometheus](https://github.com/hteppl/remnawave-prometheus) | Динамическое обнаружение целей-нод через API Remnawave (file_sd) | На будущее, если скрейпить ноды напрямую |
| [kutovoys/xray-checker](https://github.com/kutovoys/xray-checker) | Внешняя проверка доступности VLESS/Trojan + DPI-проба | На будущее |
| [prom/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) | Проба доступности эндпоинтов и API | На будущее |
| node_exporter + cAdvisor | Метрики ОС и контейнеров нод | Уже покрыто mgmt-стеком флота |
| [hteppl/remnawave-traffic-guard](https://github.com/hteppl/remnawave-traffic-guard) | Детект злоупотреблений и всплесков трафика через API + Redis | Опционально |
| [Case211/remnawave-admin](https://github.com/Case211/remnawave-admin) | Админ-панель со своим профилем мониторинга и дашбордами | Другой источник метрик, здесь не используется |

---

## <img src="assets/icons/shield-01.svg" width="24" alt="" /> Благодарности

Дашборд Grafana: [Remnawave Monitoring Dashboard](https://grafana.com/grafana/dashboards/25064) (ID 25064).

Иконки: [Hugeicons](https://hugeicons.com) (`@hugeicons/static`, лицензия MIT), завендорены в `assets/icons/` и перекрашены в акцентный зелёный.

Лицензия: MIT (см. `LICENSE`).

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

Всё слушает `127.0.0.1` на хосте панели. Доступ с рабочей машины — через SSH-туннель, заданный для `dropweb-panel`. Порт 3001 на хосте занят эндпоинтом метрик панели, поэтому Grafana публикуется на 3002; туннель отображает порт `3001` рабочей машины на `3002` хоста.

---

## <img src="assets/icons/folder-01.svg" width="24" alt="" /> Структура

```
.
├── docker-compose.yml                              # prometheus + grafana; подключается к внешней remnawave-network
├── .env                                            # GF_SECURITY_ADMIN_PASSWORD, PANEL_HOST (в .gitignore)
├── .env.example                                    # шаблон
├── deploy.sh                                       # синхронизация конфигов, рендер кредов на хосте, docker compose up -d
├── Makefile                                        # ops-команды
├── prometheus/
│   ├── prometheus.yml.tmpl                         # шаблон скрейпа; рендерится в prometheus.yml на хосте (username подставляется)
│   └── alerts.yml                                  # правила алертов
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

**Требования**

- настроенный SSH-алиас хоста `dropweb-panel`
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

---

## <img src="assets/icons/key-01.svg" width="24" alt="" /> Доступ

Открыть SSH-туннель к `dropweb-panel`, затем:

| URL | Что |
|---|---|
| `http://localhost:3001` | Grafana (логин: `admin` / `GF_SECURITY_ADMIN_PASSWORD`) |
| `http://localhost:9090` | Prometheus |

Порты `3001` и `9090` рабочей машины общие с другими туннель-хостами. Держите открытым один туннель за раз.

---

## <img src="assets/icons/chart-line-data-01.svg" width="24" alt="" /> Алерты

Заданы в `prometheus/alerts.yml`, группа `remnawave`. Вычисляются Prometheus; видны в его UI и доступны для алертинга Grafana. Alertmanager не входит в комплект — подключите его отдельно для уведомлений.

| Алерт | Выражение | For |
|---|---|---|
| `RemnawavePanelMetricsDown` | `up{job="remnawave"} == 0` | 2m |
| `RemnawaveNodeDown` | `remnawave_node_status * on(node_uuid) group_left(node_name) remnawave_node_basic_info == 0` | 3m |
| `RemnawaveAllNodesDown` | `sum(remnawave_node_status) == 0` | 2m |

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

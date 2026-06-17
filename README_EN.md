<div align="right">
  <a href="README.md">Русский</a>
</div>

# Remnawave Panel Monitoring

Self-contained Prometheus + Grafana stack for the Remnawave panel host. Attaches to the panel's existing docker network, scrapes its native metrics endpoint, and provisions dashboard 25064. Independent of any central monitoring stack.

---

## <img src="assets/icons/share-08.svg" width="24" alt="" /> Architecture

```
Remnawave panel
  remnawave:3001/metrics  (HTTP basic auth)
        |
        | docker network: remnawave-network
        v
  monitoring-prometheus   (127.0.0.1:9090, 15d retention, 512M)
        |
        v
  monitoring-grafana      (127.0.0.1:3002, 256M)
        |
        | SSH tunnel: workstation 3001 -> host 3002
        v
  browser @ localhost:3001
```

Everything binds to `127.0.0.1` on the panel host. Access from your workstation goes through the SSH tunnel defined for `dropweb-panel`. Host port 3001 is already taken by the panel's metrics endpoint, so Grafana publishes on 3002; the tunnel maps workstation `3001 -> host 3002`.

---

## <img src="assets/icons/folder-01.svg" width="24" alt="" /> Layout

```
.
├── docker-compose.yml                              # prometheus + grafana; joins external remnawave-network
├── .env                                            # GF_SECURITY_ADMIN_PASSWORD, PANEL_HOST (gitignored)
├── .env.example                                    # template
├── deploy.sh                                       # sync configs, render creds on host, docker compose up -d
├── Makefile                                        # ops shortcuts
├── prometheus/
│   ├── prometheus.yml.tmpl                         # scrape template; rendered to prometheus.yml on the host (username injected)
│   └── alerts.yml                                  # alert rules
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── prometheus.yml                      # Prometheus datasource (uid=prometheus, default)
│   │   └── dashboards/
│   │       └── provider.yml                        # file provider -> /var/lib/grafana/dashboards
│   └── dashboards/
│       └── remnawave-25064.json                    # the dashboard
└── assets/
    └── icons/                                      # vendored Hugeicons SVGs (used by this README)
```

---

## <img src="assets/icons/rocket-01.svg" width="24" alt="" /> Deploy

**Prerequisites**

- SSH host alias `dropweb-panel` configured
- Remnawave panel running with metrics enabled
- Docker network `remnawave-network` present on the host

**Steps**

```bash
cp .env.example .env
# set GF_SECURITY_ADMIN_PASSWORD (openssl rand -hex 16) and PANEL_HOST
./deploy.sh
# or target another host: ./deploy.sh other-alias
```

`deploy.sh` reads `METRICS_USER` and `METRICS_PASS` from `/opt/remnawave/.env` on the panel host, renders `prometheus.yml` (username) and `prometheus/metrics_pass` (password, chowned to `65534:65534` since Prometheus runs as `nobody`), then runs `docker compose up -d` and reloads Prometheus. No panel credentials are stored in this repo.

**Make targets**

| Target | Action |
|---|---|
| `make deploy` | run deploy.sh against HOST |
| `make ps` | docker compose ps |
| `make logs` | docker compose logs -f |
| `make down` | docker compose down |
| `make targets` | show Prometheus scrape targets |

Override host with `HOST=...`, e.g. `make deploy HOST=other-alias`.

---

## <img src="assets/icons/key-01.svg" width="24" alt="" /> Access

Open the SSH tunnel to `dropweb-panel`, then:

| URL | What |
|---|---|
| `http://localhost:3001` | Grafana (login: `admin` / `GF_SECURITY_ADMIN_PASSWORD`) |
| `http://localhost:9090` | Prometheus |

Workstation ports 3001 and 9090 are shared with other tunnel hosts. Keep one tunnel open at a time.

---

## <img src="assets/icons/chart-line-data-01.svg" width="24" alt="" /> Alerts

Defined in `prometheus/alerts.yml`, group `remnawave`. Evaluated by Prometheus; visible in its UI and usable by Grafana alerting. Alertmanager is not bundled — wire it separately for notifications.

| Alert | Expression | For |
|---|---|---|
| `RemnawavePanelMetricsDown` | `up{job="remnawave"} == 0` | 2m |
| `RemnawaveNodeDown` | `remnawave_node_status * on(node_uuid) group_left(node_name) remnawave_node_basic_info == 0` | 3m |
| `RemnawaveAllNodesDown` | `sum(remnawave_node_status) == 0` | 2m |

**Node name labels.** Remnawave v2.7.0+ moved `node_name` and country labels onto `remnawave_node_basic_info` to keep cardinality low. Join on `node_uuid` to get human-readable names in any query:

```promql
remnawave_node_online_users * on(node_uuid) group_left(node_name) remnawave_node_basic_info
```

---

## <img src="assets/icons/help-circle.svg" width="24" alt="" /> Why this isn't built into Remnawave

Remnawave exposes the metrics endpoint and publishes dashboard 25064, but deliberately does not bundle a Prometheus/Grafana stack. Three reasons:

1. **Cardinality.** Per-user history belongs in PostgreSQL, not in Prometheus time-series storage.
2. **Security/isolation.** Node metrics are aggregated by the panel rather than exposing each node externally.
3. **Separation of concerns.** Prometheus covers health and alerting only. Usage limits and traffic blocking stay in the panel backend.

This repo is operator-side glue that wires those pieces together.

---

## <img src="assets/icons/server-stack-01.svg" width="24" alt="" /> Related / future

| Tool | Use | Adopt? |
|---|---|---|
| [hteppl/remnawave-prometheus](https://github.com/hteppl/remnawave-prometheus) | Dynamic node target discovery via the Remnawave API (file_sd) | Future, if scraping nodes directly |
| [kutovoys/xray-checker](https://github.com/kutovoys/xray-checker) | External VLESS/Trojan reachability + DPI probe | Future |
| [prom/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) | Endpoint/API uptime probing | Future |
| node_exporter + cAdvisor | Node OS + container metrics | Already covered by fleet mgmt stack |
| [hteppl/remnawave-traffic-guard](https://github.com/hteppl/remnawave-traffic-guard) | Abuse/traffic-spike detection via API + Redis | Optional |
| [Case211/remnawave-admin](https://github.com/Case211/remnawave-admin) | Admin panel with its own monitoring profile + dashboards | Different metrics source, not used here |

---

## <img src="assets/icons/shield-01.svg" width="24" alt="" /> Credits

Grafana dashboard: [Remnawave Monitoring Dashboard](https://grafana.com/grafana/dashboards/25064) (ID 25064).

Icons: [Hugeicons](https://hugeicons.com) (`@hugeicons/static`, MIT license), vendored under `assets/icons/` and recolored to the project accent green.

License: MIT (see `LICENSE`).

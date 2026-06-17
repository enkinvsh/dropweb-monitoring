#!/usr/bin/env bash
# Deploy the self-contained Remnawave-panel monitoring stack.
# Operator config comes from .env (PANEL_HOST, GF_SECURITY_ADMIN_PASSWORD).
# Panel metrics creds are read from the panel's own /opt/remnawave/.env at deploy time
# and rendered on the host — never stored in this repo.
# Usage: ./deploy.sh [ssh_host]   (defaults to $PANEL_HOST)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
HOST="${1:-${PANEL_HOST:-remnawave-panel}}"
# per-host config: .env.<host> overrides .env (multi-panel support)
ENVFILE="$HERE/.env"
[ -f "$HERE/.env.$HOST" ] && ENVFILE="$HERE/.env.$HOST"
DEST="/opt/monitoring"
SSH_OPTS=(-o ClearAllForwardings=yes)

echo ">> [$HOST] ensure remote dirs"
ssh "${SSH_OPTS[@]}" "$HOST" \
  "mkdir -p $DEST/prometheus $DEST/grafana/provisioning/datasources $DEST/grafana/provisioning/dashboards $DEST/grafana/dashboards"

echo ">> sync configs"
scp -q "${SSH_OPTS[@]}" "$HERE/docker-compose.yml"                              "$HOST:$DEST/"
scp -q "${SSH_OPTS[@]}" "$HERE/prometheus/prometheus.yml.tmpl"                  "$HOST:$DEST/prometheus/"
scp -q "${SSH_OPTS[@]}" "$HERE/prometheus/alerts.yml"                           "$HOST:$DEST/prometheus/"
scp -q "${SSH_OPTS[@]}" "$HERE/grafana/provisioning/datasources/prometheus.yml" "$HOST:$DEST/grafana/provisioning/datasources/"
scp -q "${SSH_OPTS[@]}" "$HERE/grafana/provisioning/dashboards/provider.yml"    "$HOST:$DEST/grafana/provisioning/dashboards/"
scp -q "${SSH_OPTS[@]}" "$HERE"/grafana/dashboards/*.json                       "$HOST:$DEST/grafana/dashboards/"
scp -q "${SSH_OPTS[@]}" "$ENVFILE"                                            "$HOST:$DEST/.env"

echo ">> render metrics creds from the panel's /opt/remnawave/.env (nothing printed, nothing stored in repo)"
ssh "${SSH_OPTS[@]}" "$HOST" 'bash -s' <<'REMOTE'
set -e
SRC=/opt/remnawave/.env; D=/opt/monitoring/prometheus
mu=$(grep -E "^METRICS_USER=" "$SRC" | head -1 | cut -d= -f2-); mu="${mu%\"}"; mu="${mu#\"}"; mu="${mu%\'}"; mu="${mu#\'}"
mp=$(grep -E "^METRICS_PASS=" "$SRC" | head -1 | cut -d= -f2-); mp="${mp%\"}"; mp="${mp#\"}"; mp="${mp%\'}"; mp="${mp#\'}"
printf '%s' "$mp" > "$D/metrics_pass"; chown 65534:65534 "$D/metrics_pass"; chmod 600 "$D/metrics_pass"
sed "s|__METRICS_USER__|$mu|g" "$D/prometheus.yml.tmpl" > "$D/prometheus.yml"; chmod 644 "$D/prometheus.yml"
REMOTE

echo ">> docker compose up -d + reload prometheus"
ssh "${SSH_OPTS[@]}" "$HOST" "cd $DEST && docker compose up -d && docker compose restart prometheus"

echo ">> done. View:  ssh $HOST  ->  http://localhost:3001 (Grafana)"

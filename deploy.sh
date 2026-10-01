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
  "mkdir -p $DEST/prometheus $DEST/alertmanager $DEST/grafana/provisioning/datasources $DEST/grafana/provisioning/dashboards $DEST/grafana/dashboards"

echo ">> sync configs"
scp -q "${SSH_OPTS[@]}" "$HERE/docker-compose.yml"                              "$HOST:$DEST/"
scp -q "${SSH_OPTS[@]}" "$HERE/prometheus/prometheus.yml.tmpl"                  "$HOST:$DEST/prometheus/"
scp -q "${SSH_OPTS[@]}" "$HERE/prometheus/alerts.yml"                           "$HOST:$DEST/prometheus/"
scp -q "${SSH_OPTS[@]}" "$HERE/alertmanager/alertmanager.yml"                   "$HOST:$DEST/alertmanager/"
scp -q "${SSH_OPTS[@]}" "$HERE/alertmanager/tg_relay.py"                        "$HOST:$DEST/alertmanager/"
scp -q "${SSH_OPTS[@]}" "$HERE/grafana/provisioning/datasources/prometheus.yml" "$HOST:$DEST/grafana/provisioning/datasources/"
scp -q "${SSH_OPTS[@]}" "$HERE/grafana/provisioning/dashboards/provider.yml"    "$HOST:$DEST/grafana/provisioning/dashboards/"
scp -q "${SSH_OPTS[@]}" "$HERE"/grafana/dashboards/*.json                       "$HOST:$DEST/grafana/dashboards/"
scp -q "${SSH_OPTS[@]}" "$ENVFILE"                                            "$HOST:$DEST/.env"

echo ">> render metrics + telegram creds from the panel's /opt/remnawave/.env (nothing printed, nothing stored in repo)"
ssh "${SSH_OPTS[@]}" "$HOST" 'bash -s' <<'REMOTE'
set -e
SRC=/opt/remnawave/.env; D=/opt/monitoring/prometheus; A=/opt/monitoring/alertmanager
getv() { local v; v=$(grep -E "^$1=" "$SRC" | head -1 | cut -d= -f2-); v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"; printf '%s' "$v"; }
mu=$(getv METRICS_USER); mp=$(getv METRICS_PASS)
printf '%s' "$mp" > "$D/metrics_pass"; chown 65534:65534 "$D/metrics_pass"; chmod 600 "$D/metrics_pass"
sed "s|__METRICS_USER__|$mu|g" "$D/prometheus.yml.tmpl" > "$D/prometheus.yml"; chmod 644 "$D/prometheus.yml"
# telegram target = TELEGRAM_NOTIFY_NODES ("chat_id" or "chat_id:thread_id"), same chat the panel notifies
tok=$(getv TELEGRAM_BOT_TOKEN); tgt=$(getv TELEGRAM_NOTIFY_NODES)
[ -n "$tok" ] && [ -n "$tgt" ] || { echo "TELEGRAM_BOT_TOKEN / TELEGRAM_NOTIFY_NODES missing in $SRC" >&2; exit 1; }
chat="${tgt%%:*}"; thread=""; [ "$tgt" != "$chat" ] && thread="${tgt#*:}"
printf '%s' "$tok" > "$A/tg_bot_token"; chown 65534:65534 "$A/tg_bot_token"; chmod 600 "$A/tg_bot_token"
printf 'TG_CHAT=%s\nTG_THREAD=%s\n' "$chat" "$thread" > "$A/tg_relay.env"; chmod 644 "$A/tg_relay.env"
rm -f "$A/alertmanager.yml.tmpl"
REMOTE

echo ">> docker compose up -d + reload prometheus/alertmanager"
ssh "${SSH_OPTS[@]}" "$HOST" "cd $DEST && docker compose up -d && docker compose restart prometheus alertmanager tg-relay"

echo ">> done. View:  ssh $HOST  ->  http://localhost:3001 (Grafana)"

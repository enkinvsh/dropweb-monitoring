#!/usr/bin/env bash
# Interactive onboarding for the Remnawave panel monitoring stack.
# Installs your SSH key on the panel, configures the SSH tunnel, verifies the
# panel, generates a Grafana password and deploys. Run from the repo root.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== Remnawave panel monitoring — setup =="
echo

read -rp "Panel SSH host or IP: " PANEL_IP
[ -n "${PANEL_IP:-}" ] || { echo "host is required"; exit 1; }
read -rp "SSH user [root]: " SSH_USER; SSH_USER="${SSH_USER:-root}"
read -rp "SSH port [22]: " SSH_PORT; SSH_PORT="${SSH_PORT:-22}"
read -rp "SSH alias name [remnawave-panel]: " ALIAS; ALIAS="${ALIAS:-remnawave-panel}"

SSH_CFG="$HOME/.ssh/config"
mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
touch "$SSH_CFG"; chmod 600 "$SSH_CFG"
cp "$SSH_CFG" "$SSH_CFG.bak.$(date +%Y%m%d-%H%M%S)"

echo ">> writing SSH alias '$ALIAS' with the Grafana/Prometheus tunnel"
# keep every block except an existing one for this alias, drop trailing blanks
KEPT="$(awk -v a="$ALIAS" '/^[Hh]ost /{inb=($2==a)} !inb{print}' "$SSH_CFG" \
        | awk 'NF{p=NR}{l[NR]=$0}END{for(i=1;i<=p;i++)print l[i]}')"
{
  [ -n "$KEPT" ] && printf '%s\n\n' "$KEPT"
  printf 'Host %s\n' "$ALIAS"
  printf '  HostName %s\n' "$PANEL_IP"
  printf '  User %s\n' "$SSH_USER"
  printf '  Port %s\n' "$SSH_PORT"
  printf '  LocalForward 3001 127.0.0.1:3002   # Grafana\n'
  printf '  LocalForward 9090 127.0.0.1:9090   # Prometheus\n'
} > "$SSH_CFG"
chmod 600 "$SSH_CFG"

echo ">> checking SSH key access"
if ! ssh -o ConnectTimeout=8 -o BatchMode=yes -o ClearAllForwardings=yes "$ALIAS" true 2>/dev/null; then
  echo "   no key access yet — installing your public key (enter the panel password once):"
  ssh-copy-id -o ClearAllForwardings=yes "$ALIAS"
fi
ssh -o ConnectTimeout=8 -o BatchMode=yes -o ClearAllForwardings=yes "$ALIAS" true 2>/dev/null \
  || { echo "   SSH key access still failing — aborting"; exit 1; }
echo "   SSH OK"

echo ">> verifying the panel"
ssh -o ClearAllForwardings=yes "$ALIAS" 'bash -s' <<'REMOTE'
set -e
[ -f /opt/remnawave/.env ] || { echo "   FATAL: /opt/remnawave/.env missing — not a standard Remnawave panel"; exit 1; }
grep -q '^METRICS_USER=' /opt/remnawave/.env || { echo "   FATAL: METRICS_USER missing — enable panel metrics in /opt/remnawave/.env"; exit 1; }
docker network inspect remnawave-network >/dev/null 2>&1 || { echo "   FATAL: docker network 'remnawave-network' not found"; exit 1; }
echo "   panel OK"
REMOTE

ENVF="$HERE/.env.$ALIAS"
if [ -f "$ENVF" ]; then
  echo ">> $ENVF exists — keeping it"
else
  umask 077
  printf 'GF_SECURITY_ADMIN_PASSWORD=%s\nPANEL_HOST=%s\n' "$(openssl rand -hex 16)" "$ALIAS" > "$ENVF"
  echo ">> created $ENVF (generated Grafana admin password)"
fi

echo ">> deploying..."
"$HERE/deploy.sh" "$ALIAS"

GFP="$(grep '^GF_SECURITY_ADMIN_PASSWORD=' "$ENVF" | cut -d= -f2-)"
cat <<EOF

============================================================
 Done — monitoring is live on '$ALIAS'.

   View:    ssh $ALIAS    then open  http://localhost:3001
   Login:   admin / $GFP
============================================================
EOF

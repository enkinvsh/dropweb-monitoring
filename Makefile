# Remnawave panel monitoring — ops shortcuts.
# HOST defaults to PANEL_HOST from .env; override: make deploy HOST=other-alias
-include .env
HOST ?= $(or $(PANEL_HOST),remnawave-panel)
DEST := /opt/monitoring
SSH  := ssh -o ClearAllForwardings=yes $(HOST)

.PHONY: help deploy up down restart ps logs logs-prom logs-grafana targets

help:        ## list targets
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## / — /'

deploy:      ## sync configs + (re)deploy to HOST
	./deploy.sh $(HOST)

up:          ## docker compose up -d
	$(SSH) "cd $(DEST) && docker compose up -d"

down:        ## stop + remove containers (keeps volumes)
	$(SSH) "cd $(DEST) && docker compose down"

restart:     ## restart both containers
	$(SSH) "cd $(DEST) && docker compose restart"

ps:          ## container status
	$(SSH) "cd $(DEST) && docker compose ps"

logs:        ## tail both
	$(SSH) "cd $(DEST) && docker compose logs -f --tail=100"

logs-prom:   ## prometheus logs
	$(SSH) "cd $(DEST) && docker compose logs -f --tail=100 prometheus"

logs-grafana:## grafana logs
	$(SSH) "cd $(DEST) && docker compose logs -f --tail=100 grafana"

targets:     ## show prometheus scrape target health
	$(SSH) "curl -s http://127.0.0.1:9090/api/v1/targets | python3 -c \"import sys,json;[print(t['labels']['job'],t['health']) for t in json.load(sys.stdin)['data']['activeTargets']]\""

# Тонкая обёртка над репозиторием после разделения на backend/ и frontend/.
#
#   - питон-цели (gate, test, eval, demo, ...) пробрасываются в backend/Makefile;
#   - инфраструктура (docker compose) живёт здесь, рядом с docker-compose.yml;
#   - frontend/ пока только каркас — см. frontend/README.md.
#
# Переменные командной строки (m=, email=, password=, full_name=) make
# автоматически передаёт во вложенный вызов, отдельно прокидывать не нужно.

.DEFAULT_GOAL := gate

BACKEND_TARGETS := gate tasks test eval demo fmt install gate-selftest migrate migration api seed-admin

.PHONY: $(BACKEND_TARGETS) up down logs db-shell front help

$(BACKEND_TARGETS):
	$(MAKE) -C backend $@

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

db-shell:
	docker compose exec postgres psql -U $${POSTGRES_USER:-masker} -d $${POSTGRES_DB:-masker}

front:
	@echo "frontend/ — пока только каркас без сборки, см. frontend/README.md"

help:
	@echo "Питон-цели (уходят в backend/): $(BACKEND_TARGETS)"
	@echo "Инфраструктура (docker compose): up down logs db-shell"

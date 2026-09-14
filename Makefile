# Тонкая обёртка над репозиторием после разделения на backend/ и frontend/.
#
#   - питон-цели (gate, test, eval, demo, ...) пробрасываются в backend/Makefile;
#   - инфраструктура (docker compose) живёт здесь, рядом с docker-compose.yml;
#   - frontend/ — проверки веб-интерфейса (make front), см. frontend/README.md.
#
# Переменные командной строки (m=, email=, password=, full_name=) make
# автоматически передаёт во вложенный вызов, отдельно прокидывать не нужно.

.DEFAULT_GOAL := gate

BACKEND_TARGETS := gate tasks test eval bench bench-matrix demo fmt install gate-selftest migrate migration api seed-admin

.PHONY: $(BACKEND_TARGETS) up down logs db-shell front deploy deploy-check prod-logs prod-status prod-down help

$(BACKEND_TARGETS):
	$(MAKE) -C backend $@

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Дефолты — на уровне make ($(if ...)), не шелла ($${VAR:-default}): последнее
# раскрывает только POSIX sh, а на Windows без sh.exe на PATH make гонит
# рецепты через cmd.exe, который передаёт psql буквальную строку с «${...}».
db-shell:
	docker compose exec postgres psql -U $(if $(POSTGRES_USER),$(POSTGRES_USER),masker) -d $(if $(POSTGRES_DB),$(POSTGRES_DB),masker)

front:
	cd frontend && yarn install --frozen-lockfile && yarn typecheck && yarn test

# Стенд: отдельный compose-файл и свой .env.prod, чтобы дев-окружение и
# публичный стенд не делили ни секреты, ни тома. Подробности — docs/DEPLOY.md.
deploy:
	./scripts/deploy.sh up

deploy-check:
	./scripts/deploy.sh check

prod-status:
	./scripts/deploy.sh status

prod-logs:
	./scripts/deploy.sh logs

prod-down:
	./scripts/deploy.sh down

help:
	@echo "Питон-цели (уходят в backend/): $(BACKEND_TARGETS)"
	@echo "Инфраструктура (docker compose): up down logs db-shell"
	@echo "Стенд (docker-compose.prod.yml): deploy deploy-check prod-status prod-logs prod-down"

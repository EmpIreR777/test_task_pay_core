.PHONY: up down logs clean migrate

up:
	docker compose -f docker-compose.yml up -d --build
	docker compose -f docker-compose.yml logs migrator
	docker compose -f docker-compose.yml rm -f migrator

migrate:
	docker compose -f docker-compose.yml run --rm migrator

down:
	docker compose -f docker-compose.yml down

logs:
	docker compose -f docker-compose.yml logs -f

clean:
	docker compose -f docker-compose.yml down -v --remove-orphans

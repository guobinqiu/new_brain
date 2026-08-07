deploy +rest:
	just {{rest}}

build:
	docker compose -f deploy/cpu/docker-compose.yml build

up:
	docker compose -f deploy/cpu/docker-compose.yml up -d

down:
	docker compose -f deploy/cpu/docker-compose.yml down

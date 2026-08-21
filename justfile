svc action="up":
	@just _{{action}} svc

rag target="cpu" action="up":
	@just _{{action}} {{target}}

models target="all":
	@scripts/download_models.sh {{target}}

_up area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml up -d

_down area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml down

_build area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml build

_restart area:
	@just _down {{area}}
	@just _up {{area}}

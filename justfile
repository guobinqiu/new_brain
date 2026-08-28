svc action="up" target="cpu":
	@just _services {{target}} {{action}} postgres qdrant minio loki nginx promtail

rag action="up" target="cpu":
	@just _services {{target}} {{action}} rag

llm action="up" target="cpu":
	@just _services {{target}} {{action}} llm

webui action="up" target="cpu":
	@just _services {{target}} {{action}} webui

postgres action="up" target="cpu":
	@just _services {{target}} {{action}} postgres

qdrant action="up" target="cpu":
	@just _services {{target}} {{action}} qdrant

minio action="up" target="cpu":
	@just _services {{target}} {{action}} minio

loki action="up" target="cpu":
	@just _services {{target}} {{action}} loki

nginx action="up" target="cpu":
	@just _services {{target}} {{action}} nginx

promtail action="up" target="cpu":
	@just _services {{target}} {{action}} promtail

models target="all":
	@scripts/download_models.sh {{target}}

_services target action +services:
	@if [ "{{action}}" = "build" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml build {{services}}; elif [ "{{action}}" = "down" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml stop {{services}}; else docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml {{action}} -d {{services}}; fi

_up area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml up -d

_down area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml down

_build area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml build

_restart area:
	@just _down {{area}}
	@just _up {{area}}

svc action="up" target="cpu":
	@just _services {{target}} {{action}} postgres qdrant opensearch minio loki promtail

rag action="up" target="cpu":
	@just _services {{target}} {{action}} rag

llm action="up" target="cpu":
	@just _services {{target}} {{action}} llm

webui action="up" target="cpu":
	@if [ "{{action}}" = "build" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/cpu/docker-compose.yml run --rm --no-deps webui sh -c "npm install && npm run build"; else just _services {{target}} {{action}} webui; fi

postgres action="up" target="cpu":
	@just _services {{target}} {{action}} postgres

qdrant action="up" target="cpu":
	@just _services {{target}} {{action}} qdrant

opensearch action="up" target="cpu":
	@just _services {{target}} {{action}} opensearch

milvus action="up" target="cpu":
	@just _services {{target}} {{action}} etcd milvus

minio action="up" target="cpu":
	@just _services {{target}} {{action}} minio

loki action="up" target="cpu":
	@just _services {{target}} {{action}} loki

nginx action="up" target="cpu":
	@just _services {{target}} {{action}} nginx

promtail action="up" target="cpu":
	@just _services {{target}} {{action}} promtail

models target="all":
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/cpu/docker-compose.yml run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" -e RAG_VENV=/app/.venv rag /app/scripts/download_models.sh {{target}}

_services target action +services:
	@if [ "{{action}}" = "build" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml build {{services}}; elif [ "{{action}}" = "down" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml stop {{services}}; elif [ "{{action}}" = "restart" ]; then docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml restart {{services}}; else docker compose --env-file "$PWD/deploy/.env" -f deploy/{{target}}/docker-compose.yml {{action}} -d {{services}}; fi

_up area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml up -d

_down area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml down

_build area:
	@docker compose --env-file "$PWD/deploy/.env" -f deploy/{{area}}/docker-compose.yml build

_restart area:
	@just _down {{area}}
	@just _up {{area}}

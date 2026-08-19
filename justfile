deploy target="cpu" action="up":
	@just _deploy_{{target}}_{{action}}

worker:
	@cd backend && REDIS_URL=${REDIS_URL:-redis://localhost:16379/0} CONFIG_FILE=${CONFIG_FILE:-local.yaml} S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-http://localhost:19000} .venv/bin/celery -A indexing.celery_app:celery_app worker --pool=solo --concurrency=1 --queues index --loglevel=INFO

_deploy_cpu_up:
	@docker compose -f deploy/cpu/docker-compose.yml up -d

_deploy_cpu_down:
	@docker compose -f deploy/cpu/docker-compose.yml down

_deploy_cpu_build:
	@docker compose -f deploy/cpu/docker-compose.yml build

_deploy_cpu_restart: _deploy_cpu_down _deploy_cpu_up

_deploy_gpu_up:
	@docker compose -f deploy/gpu/docker-compose.yml up -d

_deploy_gpu_down:
	@docker compose -f deploy/gpu/docker-compose.yml down

_deploy_gpu_build:
	@docker compose -f deploy/gpu/docker-compose.yml build

_deploy_gpu_restart: _deploy_gpu_down _deploy_gpu_up

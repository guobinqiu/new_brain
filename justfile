deploy target="cpu" action="up":
	@just _deploy_{{target}}_{{action}}

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

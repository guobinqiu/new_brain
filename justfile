set dotenv-load := true
set dotenv-path := "deploy/.env"

CTRL_STACK := "brain_ctrl"
DEPLOY_STACK := "brain"
INFRA_STACK := "brain_infra"
NETWORK := "brain-net"
ROOT := justfile_directory()

ctrl action:
	just _ctrl-{{action}}

deploy action:
	just _deploy-{{action}}

infra action:
	just _infra-{{action}}

_ctrl-up: _network-up
	env PROJECT_ROOT={{quote(ROOT)}} docker stack deploy --with-registry-auth -c deploy/ctrl.yaml {{CTRL_STACK}}

_ctrl-down:
	docker stack rm {{CTRL_STACK}}

_deploy-up: _network-up
	env PROJECT_ROOT={{quote(ROOT)}} docker stack deploy --with-registry-auth -c deploy/deploy.yaml {{DEPLOY_STACK}}

_deploy-down:
	docker stack rm {{DEPLOY_STACK}}

_infra-up: _network-up
	env PROJECT_ROOT={{quote(ROOT)}} docker stack deploy --with-registry-auth -c deploy/infra.yaml {{INFRA_STACK}}

_infra-down:
	docker stack rm {{INFRA_STACK}}

_network-up:
	docker network inspect {{NETWORK}} >/dev/null 2>&1 || docker network create --driver overlay --attachable {{NETWORK}}

service action name:
	just _service-{{action}} {{quote(name)}}

_service-start name:
	docker service scale {{quote(name)}}=1

_service-stop name:
	docker service scale {{quote(name)}}=0

_service-remove name:
	docker service rm {{quote(name)}}

_service-rollout name:
	docker service update --force {{quote(name)}}

bundle service:
	npm --prefix {{quote(service)}} run build

build service:
	docker build -f deploy/Dockerfile --target {{quote(service)}} \
	  -t {{quote(env_var("IMAGE_REGISTRY") + "/brain-" + service + ":" + env_var("IMAGE_TAG"))}} \
	  --build-arg USE_CN_MIRROR={{quote(env_var_or_default("USE_CN_MIRROR", "true"))}} \
	  --build-arg SERVICE_EXTRA={{quote(env_var_or_default("SERVICE_EXTRA", "cpu"))}} .

push service:
	docker push {{quote(env_var("IMAGE_REGISTRY") + "/brain-" + service + ":" + env_var("IMAGE_TAG"))}}

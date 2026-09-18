set dotenv-load := true
set dotenv-path := "deploy/.env"

CTRL_STACK := "brain_ctrl"
DEPLOY_STACK := "brain"
NETWORK := "brain-net"
ROOT := justfile_directory()
RAG_IMAGE := env_var_or_default("RAG_IMAGE", "brain-rag:dev")
PARSER_IMAGE := env_var_or_default("PARSER_IMAGE", "brain-parser:dev")
INFERENCE_IMAGE := env_var_or_default("INFERENCE_IMAGE", "brain-inference:dev")
LLM_IMAGE := env_var_or_default("LLM_IMAGE", "brain-llm:dev")
OPS_IMAGE := env_var_or_default("OPS_IMAGE", "brain-ops:dev")

ctrl action:
	just _ctrl-{{action}}

deploy action:
	just _deploy-{{action}}

_ctrl-up: _network-up
	env PROJECT_ROOT={{quote(ROOT)}} docker stack deploy --with-registry-auth -c deploy/ctrl.yaml {{CTRL_STACK}}

_ctrl-down:
	docker stack rm {{CTRL_STACK}}

_deploy-up: _network-up
	env PROJECT_ROOT={{quote(ROOT)}} docker stack deploy --with-registry-auth -c deploy/deploy.yaml {{DEPLOY_STACK}}

_deploy-down:
	docker stack rm {{DEPLOY_STACK}}

_network-up:
	docker network inspect {{NETWORK}} >/dev/null 2>&1 || docker network create --driver overlay --attachable {{NETWORK}}

_service-start service:
	docker service scale {{service}}=1

_service-stop service:
	docker service scale {{service}}=0

_service-remove service:
	docker service rm {{service}}

_service-rollout service:
	docker service update --force {{service}}

webui action:
	just _webui-{{action}}

rag action:
	just _rag-{{action}}

parser action:
	just _parser-{{action}}

inference action:
	just _inference-{{action}}

llm action:
	just _llm-{{action}}

ops action:
	just _ops-{{action}}

_rag-build:
	docker build -f deploy/Dockerfile --target rag -t {{ RAG_IMAGE }} --build-arg USE_CN_MIRROR={{ env_var_or_default("USE_CN_MIRROR", "true") }} .

_rag-push:
	docker push {{ RAG_IMAGE }}

_rag-start:
	just _service-start brain_rag

_rag-stop:
	just _service-stop brain_rag

_rag-remove:
	just _service-remove brain_rag

_rag-rollout:
	just _service-rollout brain_rag

_parser-build:
	docker build -f deploy/Dockerfile --target parser -t {{ PARSER_IMAGE }} --build-arg USE_CN_MIRROR={{ env_var_or_default("USE_CN_MIRROR", "true") }} --build-arg SERVICE_EXTRA={{ env_var_or_default("SERVICE_EXTRA", "cpu") }} .

_parser-push:
	docker push {{ PARSER_IMAGE }}

_parser-start:
	just _service-start brain_parser

_parser-stop:
	just _service-stop brain_parser

_parser-remove:
	just _service-remove brain_parser

_parser-rollout:
	just _service-rollout brain_parser

_inference-build:
	docker build -f deploy/Dockerfile --target inference -t {{ INFERENCE_IMAGE }} --build-arg USE_CN_MIRROR={{ env_var_or_default("USE_CN_MIRROR", "true") }} --build-arg SERVICE_EXTRA={{ env_var_or_default("SERVICE_EXTRA", "cpu") }} .

_inference-push:
	docker push {{ INFERENCE_IMAGE }}

_inference-start:
	just _service-start brain_inference

_inference-stop:
	just _service-stop brain_inference

_inference-remove:
	just _service-remove brain_inference

_inference-rollout:
	just _service-rollout brain_inference

_llm-build:
	docker build -f services/llm/Dockerfile -t {{ LLM_IMAGE }} --build-arg USE_CN_MIRROR={{ env_var_or_default("USE_CN_MIRROR", "true") }} .

_llm-push:
	docker push {{ LLM_IMAGE }}

_llm-start:
	just _service-start brain_llm

_llm-stop:
	just _service-stop brain_llm

_llm-remove:
	just _service-remove brain_llm

_llm-rollout:
	just _service-rollout brain_llm

_ops-build:
	docker build -f deploy/Dockerfile --target ops -t {{ OPS_IMAGE }} --build-arg USE_CN_MIRROR={{ env_var_or_default("USE_CN_MIRROR", "true") }} .

_ops-push:
	docker push {{ OPS_IMAGE }}

_ops-start:
	just _service-start brain_ctrl_ops

_ops-stop:
	just _service-stop brain_ctrl_ops

_ops-remove:
	just _service-remove brain_ctrl_ops

_ops-rollout:
	just _service-rollout brain_ctrl_ops

_webui-build:
	npm --prefix webui run build

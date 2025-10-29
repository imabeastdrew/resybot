DOCKER ?= docker
REGISTRY ?= ghcr.io/your-org
IMAGE_PREFIX ?= resybot

RUNNER_IMAGE ?= $(REGISTRY)/$(IMAGE_PREFIX)-runner:latest
SERVER_IMAGE ?= $(REGISTRY)/$(IMAGE_PREFIX)-server:latest

.PHONY: build-runner build-server push-runner push-server

build-runner:
	$(DOCKER) build -t $(RUNNER_IMAGE) -f infra/docker/runner/Dockerfile .

build-server:
	$(DOCKER) build -t $(SERVER_IMAGE) -f infra/docker/server/Dockerfile .

push-runner:
	$(DOCKER) push $(RUNNER_IMAGE)

push-server:
	$(DOCKER) push $(SERVER_IMAGE)


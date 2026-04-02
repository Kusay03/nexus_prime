SHELL := /bin/bash

PODMAN_COMPOSE_TEST := podman-compose -f podman-compose.test.yml

.PHONY: frontend-install frontend-build frontend-lint api-dev-deps test-stack-up test-stack-down test-stack-logs test

frontend-install:
	npm --prefix frontend ci

frontend-build:
	npm --prefix frontend run build

frontend-lint:
	npm --prefix frontend run lint

api-dev-deps:
	python -m pip install -r api/requirements-dev.txt

test-stack-up:
	$(PODMAN_COMPOSE_TEST) up -d

test-stack-down:
	$(PODMAN_COMPOSE_TEST) down -v

test-stack-logs:
	$(PODMAN_COMPOSE_TEST) logs

test:
	pytest -q

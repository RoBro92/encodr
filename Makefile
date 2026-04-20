PYTHON ?= python3
PYTEST ?= pytest

.PHONY: help bootstrap api worker worker-agent ui-install ui ui-test ui-build lint format dev-up version release-check test-unit test-integration test-e2e test-security test-all check

help:
	@printf "Targets:\n"
	@printf "  bootstrap     Copy .env/config working files if missing\n"
	@printf "  api           Run the API locally\n"
	@printf "  worker        Run the local worker locally\n"
	@printf "  worker-agent  Run the remote worker-agent heartbeat once\n"
	@printf "  ui-install    Install UI dependencies\n"
	@printf "  ui            Run the UI locally\n"
	@printf "  ui-test       Run the frontend test suite\n"
	@printf "  ui-build      Build the frontend\n"
	@printf "  lint          Run lightweight sanity checks\n"
	@printf "  dev-up        Start the local Compose stack\n"
	@printf "  version       Print the current Encodr release version\n"
	@printf "  release-check Run the release validation set and print manual release steps\n"
	@printf "  test-unit     Run the unit test layer\n"
	@printf "  test-integration Run the integration test layer\n"
	@printf "  test-e2e      Run the end-to-end test layer\n"
	@printf "  test-security Run security-focused tests across layers\n"
	@printf "  test-all      Run the full test suite\n"
	@printf "  check         Run Python tests, UI tests/build, and compile checks\n"

bootstrap:
	./infra/scripts/bootstrap.sh

api:
	cd apps/api && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd apps/worker && $(PYTHON) -m app.main

worker-agent:
	cd apps/worker-agent && $(PYTHON) -m app.main

ui-install:
	cd apps/ui && npm install

ui:
	cd apps/ui && npm run dev -- --host 0.0.0.0 --port 5173

ui-test:
	cd apps/ui && npm test -- --run

ui-build:
	cd apps/ui && npm run build

lint:
	./infra/scripts/lint.sh

dev-up:
	./infra/scripts/dev-up.sh

version:
	@cat VERSION

release-check:
	./infra/scripts/release-check.sh

test-unit:
	$(PYTEST) -m unit

test-integration:
	$(PYTEST) -m integration

test-e2e:
	$(PYTEST) -m e2e

test-security:
	$(PYTEST) -m security

test-all:
	$(PYTEST)

check: test-all ui-test ui-build
	$(PYTHON) -m compileall apps packages tests

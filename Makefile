PYTHON ?= python3
PYTEST ?= pytest

.PHONY: help api worker worker-agent ui lint format dev-up test-unit test-integration test-e2e test-security test-all

help:
	@printf "Targets:\n"
	@printf "  api           Run the API placeholder locally\n"
	@printf "  worker        Run the worker placeholder locally\n"
	@printf "  worker-agent  Run the worker-agent placeholder locally\n"
	@printf "  ui            Run the UI placeholder locally\n"
	@printf "  lint          Run placeholder lint script\n"
	@printf "  dev-up        Start the scaffolded Compose stack\n"
	@printf "  test-unit     Run the unit test layer\n"
	@printf "  test-integration Run the integration test layer\n"
	@printf "  test-e2e      Run the end-to-end test layer\n"
	@printf "  test-security Run security-focused tests across layers\n"
	@printf "  test-all      Run the full test suite\n"

api:
	cd apps/api && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd apps/worker && $(PYTHON) -m app.main

worker-agent:
	cd apps/worker-agent && $(PYTHON) -m app.main

ui:
	cd apps/ui && npm run dev -- --host 0.0.0.0 --port 5173

lint:
	./infra/scripts/lint.sh

dev-up:
	./infra/scripts/dev-up.sh

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

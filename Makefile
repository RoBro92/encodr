PYTHON ?= python3

.PHONY: help api worker worker-agent ui lint format dev-up

help:
	@printf "Targets:\n"
	@printf "  api           Run the API placeholder locally\n"
	@printf "  worker        Run the worker placeholder locally\n"
	@printf "  worker-agent  Run the worker-agent placeholder locally\n"
	@printf "  ui            Run the UI placeholder locally\n"
	@printf "  lint          Run placeholder lint script\n"
	@printf "  dev-up        Start the scaffolded Compose stack\n"

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


.PHONY: dev seed-ingest build-edition refresh-kpis send-newsletter test

dev:
	./scripts/dev.sh

seed-ingest:
	cd backend && . .venv/bin/activate && python -m app.cli ingest

build-edition:
	cd backend && . .venv/bin/activate && python -m app.cli build-edition

refresh-kpis:
	cd backend && . .venv/bin/activate && python -m app.cli refresh-kpis

send-newsletter:
	cd backend && . .venv/bin/activate && python -m app.cli send-newsletter

test:
	cd backend && . .venv/bin/activate && pytest

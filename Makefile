.PHONY: install dev sandbox test build serve worker
install:
	cd backend && uv sync --python 3.12
	cd frontend && pnpm install --frozen-lockfile

worker:
	cd backend && uv run python -m arena.worker --workers 4

dev:
	python3 scripts/dev.py

sandbox:
	docker build -t campus-arena-bot:local backend/sandbox

test:
	cd backend && uv run python -m pytest -q
	cd frontend && pnpm lint
	cd frontend && pnpm build

build:
	cd frontend && pnpm build

serve: build
	cd backend && uv run uvicorn arena.app:app --host 127.0.0.1 --port 8001

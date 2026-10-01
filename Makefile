# VoltQueue — works with GNU make on Windows (cmd/Git Bash), macOS and Linux.
# Quick start:  make install && make seed && make dev

ifeq ($(OS),Windows_NT)
  PY := $(CURDIR)/backend/.venv/Scripts/python.exe
else
  PY := $(CURDIR)/backend/.venv/bin/python
endif

.PHONY: install dev dev-backend dev-frontend docker-up docker-down migrate seed test test-backend test-frontend e2e

install:  ## create backend venv + install deps, install frontend deps
	python -m venv backend/.venv
	"$(PY)" -m pip install -e "backend[dev]"
	npm --prefix frontend install

dev:  ## backend (:8000, /health) + frontend (:5173) in one terminal
	"$(PY)" scripts/dev.py

dev-backend:
	cd backend && "$(PY)" -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	npm --prefix frontend run dev

docker-up:  ## same stack via Docker Compose (add `--profile postgres` for PostgreSQL)
	docker compose up --build

docker-down:
	docker compose down

migrate:
	cd backend && "$(PY)" -m alembic upgrade head

seed: migrate  ## apply migrations, then insert demo data (idempotent)
	cd backend && "$(PY)" -m app.seed

test: test-backend test-frontend

test-backend:
	cd backend && "$(PY)" -m pytest -q

test-frontend:
	npm --prefix frontend run typecheck

e2e:  ## Playwright: replay the PRD 7.3 demo on its own backend (:8100) and Vite (:5174); needs Chrome
	npm --prefix frontend run e2e

# Apex Intel — Developer Makefile
# Usage: make <target>

.PHONY: help up down build test lint migrate seed train backtest logs clean e2e-up e2e-down up-e2e

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m

help:  ## Show this help
	@echo ""
	@echo "$(BOLD)Apex Intel — Available Commands$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────

up:  ## Start all services (dev mode)
	docker compose up -d --build
	@echo "$(GREEN)✓ Services started$(RESET)"
	@echo "  Dashboard:  http://localhost:3000"
	@echo "  API docs:   http://localhost:8000/docs"
	@echo "  Flower:     http://localhost:5555"

up-dev:  ## Dev stack (compose default + hot reload overlay if present)
	docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build

up-test:  ## Isolated Timescale+Redis (no prod volume)
	docker compose -f docker-compose.test.yml --profile test up -d

up-e2e: e2e-up  ## qa-e2e stack (does not touch the dev project)

e2e-up:  ## Start qa-e2e, migrate, and seed demo prices
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/e2e-up.ps1

e2e-down:  ## Stop qa-e2e and keep the named volume
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/e2e-down.ps1

up-prod-like:  ## Same images as intended server (prod overlay)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

seed-golden:  ## Copy 01B goldens into backend/data/golden_seed (paper)
	python scripts/seed_golden_portfolios.py

backup-verify:  ## Local dump/restore count check
	python scripts/backup_verify.py

audit:  ## Validity audit → docs/audits/phase0-validity.json
	python validation/run_audit.py

check:  ## Local gates without docker
	python scripts/orphan_check.py --check
	python scripts/architecture_lint.py --check
	cd backend && python -m pytest app/tests/test_baseline_guards.py app/tests/test_phase0_ops.py app/tests/test_golden_portfolios.py -q --tb=line

up-prod:  ## Start all services (production mode)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

down:  ## Stop all services
	docker compose down

down-v:  ## Stop all services and remove volumes (⚠ destroys data)
	docker compose down -v

build:  ## Rebuild all images
	docker compose build --no-cache

restart:  ## Restart all services
	docker compose restart

ps:  ## Show running services
	docker compose ps

logs:  ## Tail all service logs
	docker compose logs -f --tail=100

logs-backend:  ## Tail backend logs
	docker compose logs -f backend --tail=100

logs-celery:  ## Tail celery worker logs
	docker compose logs -f celery-pipeline celery-execution --tail=100

# ── Database ──────────────────────────────────────────────────────────────────

migrate:  ## Run Alembic migrations
	docker compose exec backend alembic upgrade head

migrate-new:  ## Create a new migration (MSG="description")
	docker compose exec backend alembic revision --autogenerate -m "$(MSG)"

migrate-down:  ## Rollback one migration
	docker compose exec backend alembic downgrade -1

migrate-history:  ## Show migration history
	docker compose exec backend alembic history --verbose

seed:  ## Seed database with admin user and default watchlist
	docker compose exec backend python /app/../scripts/seed.py

seed-ingest:  ## Seed + fetch initial market data
	docker compose exec backend python /app/../scripts/seed.py --ingest

psql:  ## Open PostgreSQL shell
	docker compose exec postgres psql -U apex -d apex_intel

redis-cli:  ## Open Redis CLI
	docker compose exec redis redis-cli

# ── Testing ───────────────────────────────────────────────────────────────────

test:  ## Run all backend tests
	docker compose exec backend pytest tests/ -v --tb=short

test-unit:  ## Run unit tests only
	docker compose exec backend pytest tests/unit/ -v --tb=short -m "not slow"

test-integration:  ## Run integration tests only
	docker compose exec backend pytest tests/integration/ -v --tb=short

test-cov:  ## Run tests with coverage report
	docker compose exec backend pytest tests/ --cov=app --cov-report=term-missing --cov-report=html

test-watch:  ## Run tests in watch mode (requires pytest-watch)
	docker compose exec backend ptw tests/ -- -v --tb=short

# ── Code quality ──────────────────────────────────────────────────────────────

lint:  ## Lint backend Python code
	docker compose exec backend ruff check app/ tests/
	docker compose exec backend ruff format app/ tests/ --check

lint-fix:  ## Auto-fix lint issues
	docker compose exec backend ruff check app/ tests/ --fix
	docker compose exec backend ruff format app/ tests/

typecheck:  ## Run mypy type checking
	docker compose exec backend mypy app/ --ignore-missing-imports

lint-frontend:  ## Lint frontend TypeScript code
	docker compose exec frontend npm run lint

# ── ML Models ─────────────────────────────────────────────────────────────────

train:  ## Train direction model on SPY (730 days)
	docker compose exec backend python /scripts/train_models.py --ticker SPY --days 730

train-multi:  ## Train model on multiple tickers
	docker compose exec backend python /scripts/train_models.py --multi --days 730

# ── Backtesting ───────────────────────────────────────────────────────────────

backtest:  ## Run momentum backtest on AAPL (requires TICKER= START= END=)
	docker compose exec backend python /scripts/run_backtest.py \
		--ticker $(or $(TICKER),AAPL) \
		--strategy $(or $(STRATEGY),momentum_ml) \
		--start $(or $(START),2023-01-01) \
		--end $(or $(END),2024-12-31) \
		--save

# ── Pipeline ──────────────────────────────────────────────────────────────────

pipeline:  ## Trigger pipeline via API (requires TOKEN=)
	@if [ -z "$(TOKEN)" ]; then echo "Usage: make pipeline TOKEN=<jwt>"; exit 1; fi
	curl -s -X POST http://localhost:8000/api/v1/pipeline/run \
		-H "Authorization: Bearer $(TOKEN)" \
		-H "Content-Type: application/json" \
		-d '{}' | python3 -m json.tool

health:  ## Check API health
	curl -s http://localhost:8000/api/v1/health | python3 -m json.tool

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:  ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean  ## Remove all generated files including node_modules
	rm -rf frontend/node_modules frontend/.next
	rm -rf backend/htmlcov backend/.coverage

.DEFAULT_GOAL := help

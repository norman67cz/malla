.PHONY: help bootstrap doctor install install-dev test test-cov lint format clean build upload docs serve-docs ssh-check deploy-remote
.DEFAULT_GOAL := help
UV_CACHE_DIR := $(CURDIR)/.uv-cache
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv

bootstrap: ## Check local prerequisites and print next steps
	./scripts/bootstrap_dev.sh

doctor: bootstrap ## Alias for bootstrap

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in development mode
	$(UV) sync

install-dev: ## Install with development dependencies
	$(UV) sync --dev

test: ## Run tests
	$(UV) run pytest

test-cov: ## Run tests with coverage
	$(UV) run pytest --cov=src/malla --cov-report=html --cov-report=term

lint: ## Run linting tools
	$(UV) run ruff check src tests
	$(UV) run basedpyright src

format: ## Format code
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

clean: ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean ## Build the package
	$(UV) build

upload: build ## Upload to PyPI (requires authentication)
	$(UV) publish

docs: ## Build documentation
	@echo "Documentation build not yet configured"

serve-docs: ## Serve documentation locally
	@echo "Documentation serving not yet configured"

run-web: ## Run the web UI
	./malla-web

run-capture: ## Run the MQTT capture tool
	./malla-capture

dev-setup: install-dev ## Set up development environment
	$(UV) run pre-commit install

check: lint test ## Run all checks (lint + test)

ci: install-dev check ## Run CI pipeline locally

ssh-check: ## Verify SSH connectivity to the remote Docker host
	ssh $${DEPLOY_USER:+$${DEPLOY_USER}@}$${DEPLOY_HOST:-10.5.0.71} true

deploy-remote: ## Sync the repo to the remote host and rebuild with Docker Compose
	./scripts/deploy_remote.sh

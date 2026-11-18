.PHONY: help venv install test lint lint-fix clean dev dev-reset dev-up dev-down dev-logs dev-restart release

# Home Assistant 2026.9 needs Python 3.14; a newer default python3 cannot resolve it.
PYTHON := $(shell command -v python3.14 || command -v python3 || command -v python)
VENV := venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP := $(VENV_BIN)/pip

help:
	@echo "Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Run a ready-made test instance from the venv: a simulated"
	@echo "                      sun with a forecast and five test consumers (user dev/dev)"
	@echo "  make dev-reset    - Forget the test instance, so the next make dev starts fresh"
	@echo "  make dev-up       - Start local Home Assistant in Docker (pulls the latest image)"
	@echo "  make dev-down     - Stop local Home Assistant"
	@echo "  make dev-logs     - Follow Home Assistant logs"
	@echo "  make dev-restart  - Restart after code changes"
	@echo ""
	@echo "Testing:"
	@echo "  make venv     - Create virtual environment"
	@echo "  make install  - Install test dependencies (creates venv if needed)"
	@echo "  make test     - Run tests"
	@echo "  make lint     - Run linter"
	@echo "  make lint-fix - Run linter and apply fixes"
	@echo "  make clean    - Clean cache files"
	@echo ""
	@echo "Release:"
	@echo "  make release  - Start the release workflow: minor if a feat commit"
	@echo "                  landed since the last release, else patch."
	@echo "                  Override with VERSION=1.2.3, major, minor or patch"

venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
		echo "Virtual environment created at ./$(VENV)"; \
		echo "To activate: source $(VENV_BIN)/activate"; \
	else \
		echo "Virtual environment already exists"; \
	fi

install: venv
	@echo "Installing dependencies in virtual environment..."
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements_test.txt
	$(VENV_PIP) install ruff
	@echo "Done! Activate with: source $(VENV_BIN)/activate"

test:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	$(VENV_PYTHON) -m pytest tests/ -v

lint:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	$(VENV_BIN)/ruff check custom_components/ tests/ dev/

lint-fix:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	$(VENV_BIN)/ruff check --fix custom_components/ tests/ dev/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf $(VENV)

release:
	@# The workflow releases origin/main, so that is what the bump is read from.
	@git fetch --quiet --tags origin main
	@if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
		echo "Uncommitted changes would not be released. Commit and push them first." >&2; \
		exit 1; \
	fi
	@ahead=$$(git rev-list --count origin/main..HEAD); \
	if [ "$$ahead" -gt 0 ]; then \
		echo "$$ahead local commit(s) not on origin/main would not be released. Push them first." >&2; \
		exit 1; \
	fi
	@version="$(VERSION)"; \
	if [ -z "$$version" ]; then \
		last=$$(git describe --tags --abbrev=0 --match 'v*' origin/main 2>/dev/null); \
		if [ -z "$$last" ]; then \
			echo "No release yet, pass the first version: make release VERSION=1.2.3" >&2; \
			exit 1; \
		fi; \
		if git log --format=%s "$$last..origin/main" | grep -qE '^feat(\(.*\))?!?:'; then \
			version=minor; \
		else \
			version=patch; \
		fi; \
		echo "Releasing a $$version: commits since $$last decide it"; \
	fi; \
	gh workflow run release.yml -f version="$$version"
	@echo "Release workflow started. Follow it with: gh run watch"

# The test instance runs from the venv, which has Home Assistant and its
# frontend. configuration.yaml is the template, every time; the rest of
# config/ (users, entries, history) stays until `make dev-reset`.
dev:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	@# An older setup linked the whole directory; the links below would land
	@# in the integration's own source then.
	@if [ -L config/custom_components ]; then rm config/custom_components; fi
	@mkdir -p config/custom_components
	@cp config.template.yaml config/configuration.yaml
	@touch config/automations.yaml config/scripts.yaml config/scenes.yaml config/secrets.yaml
	@ln -sfn ../../custom_components/solar_surplus config/custom_components/solar_surplus
	@ln -sfn ../../dev/dev_solar config/custom_components/dev_solar
	@# An instance already running on this configuration is stopped, so this
	@# one takes over. Home Assistant names it in its lock file.
	@pid=$$(sed -n 's/.*"pid": *\([0-9]*\).*/\1/p' config/.ha_run.lock 2>/dev/null); \
	if [ -n "$$pid" ] && kill -0 $$pid 2>/dev/null; then \
		echo "Stopping the instance already running ($$pid)..."; \
		kill $$pid; \
		for i in $$(seq 1 60); do kill -0 $$pid 2>/dev/null || break; sleep 1; done; \
	fi
	@echo "Home Assistant on http://localhost:8123, user dev, password dev"
	@$(VENV_PYTHON) dev/provision.py & \
	$(VENV_BIN)/hass -c config

dev-reset:
	find config -mindepth 1 ! -name .gitkeep -delete
	@echo "The next make dev sets the test instance up from scratch."

dev-up:
	@echo "Starting Home Assistant..."
	@echo "Setting up configuration..."
	@mkdir -p config
	@cp -n config.template.yaml config/configuration.yaml 2>/dev/null || true
	@touch config/automations.yaml config/scripts.yaml config/scenes.yaml config/secrets.yaml 2>/dev/null || true
	@echo "Access at: http://localhost:8123"
	@echo "Checking for a newer Home Assistant image..."
	@# `stable` is a moving tag, and docker keeps serving whatever it cached
	@# the first time. Without this the container silently stays on an old
	@# release and the integration fails to import APIs that exist upstream.
	docker-compose pull
	docker-compose up -d
	@echo ""
	@echo "Waiting for Home Assistant to start..."
	@sleep 5
	docker-compose logs -f --tail=50

dev-down:
	docker-compose down

dev-logs:
	docker-compose logs -f

dev-restart:
	@echo "Restarting Home Assistant..."
	docker-compose restart
	@sleep 2
	docker-compose logs -f --tail=50

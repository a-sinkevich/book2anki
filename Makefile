VENV_DIR := .venv
ifeq ($(OS),Windows_NT)
    PYTHON := $(VENV_DIR)/Scripts/python
else
    PYTHON := $(VENV_DIR)/bin/python
endif

.PHONY: lint typecheck test build binary check clean install-dev

lint:
	$(PYTHON) -m flake8 book2anki/ tests/

typecheck:
	$(PYTHON) -m mypy book2anki/

test:
	$(PYTHON) -m pytest tests/ -v

build: check
	$(PYTHON) -m build
	@echo "Build artifacts in dist/"

binary: check
	$(PYTHON) -m shiv -c book2anki -o book2anki.pyz . --compressed
	@echo "Standalone binary: book2anki.pyz"

check: lint typecheck test
	@echo "All checks passed."

clean:
	rm -rf dist/ build/ *.egg-info book2anki.pyz .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

install-dev:
	$(PYTHON) -m pip install -e ".[dev]" shiv build

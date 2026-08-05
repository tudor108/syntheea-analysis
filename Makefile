.PHONY: install test lint run clean
install:
	python -m pip install -e ".[dev]"
test:
	python -m pytest
lint:
	python -m ruff check src tests
run:
	python -m prostate_journey.cli run-all --cohort-size 1000
clean:
	powershell -ExecutionPolicy Bypass -File scripts/clean_outputs.ps1


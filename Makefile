.PHONY: install install-ai format format-check lint type test industry docs secrets check run candidate science simulation predictive presentation app-check serve ai-catalogue ai-sync ai-check ai-specialist-check ai-demo ai-offline-eval ai-live-eval ai-accessibility ai-serve docker-build docker-up docker-down clean
install:
	uv sync --frozen --extra dev
install-ai:
	uv sync --frozen --extra dev --extra ai
format:
	uv run ruff format src tests eda
format-check:
	uv run ruff format --check src tests eda
lint:
	uv run ruff check src tests eda
type:
	uv run mypy src
test:
	uv run pytest
industry:
	uv run prostate-journey industry-check --allow-missing-release
docs:
	uv run python scripts/check_markdown_links.py --root .
secrets:
	uv run python scripts/check_no_secrets.py --root .
check: format-check lint type test industry docs secrets
run:
	uv run prostate-journey run-all --config configs/prostate_scenario_quick.yaml
candidate:
	uv run prostate-journey final-release --config configs/prostate_scenario.yaml --release-name BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1
science:
	uv run prostate-journey scientific-evidence --dataset-dir data/releases/BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1/analytical_dataset
simulation:
	uv run prostate-journey simulation-study --release BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1 --output-dir outputs/simulations/BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1
predictive:
	uv run prostate-journey predictive-evidence --dataset-dir data/releases/BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1/analytical_dataset
presentation:
	uv run prostate-journey presentation-package
app-check:
	uv run prostate-journey application-check
serve:
	uv run prostate-journey serve
ai-catalogue:
	uv run --extra ai prostate-journey ai-catalogue
ai-sync:
	uv run --extra ai prostate-journey ai-sync-vector-store
ai-check:
	uv run --extra ai prostate-journey ai-check
ai-specialist-check:
	uv run --extra ai prostate-journey ai-specialist-check
ai-demo:
	uv run --extra ai prostate-journey ai-demo-package --confirm-run
ai-offline-eval:
	uv run --extra ai prostate-journey ai-offline-eval
ai-live-eval:
	uv run --extra ai prostate-journey ai-live-eval
ai-accessibility:
	uv run python scripts/check_ai_studio_accessibility.py
ai-serve:
	uv run --extra ai prostate-journey ai-studio
docker-build:
	docker build --tag prostate-journey-analytics:local .
docker-up:
	docker compose up --build
docker-down:
	docker compose down
clean:
	powershell -ExecutionPolicy Bypass -File scripts/clean_outputs.ps1

# Local application runbook

> **SYNTHETIC SCENARIO DATA ONLY.** This runbook does not authorize real patient data,
> production use, clinical use, treatment recommendations, or claims about Bayer populations.

## Supported local runtime

- CPython 3.11 through 3.13; `.python-version` selects 3.11.9.
- `uv` 0.11.16 is the CI and container resolver version.
- Docker Desktop with Compose v2 is optional for container execution.
- No AWS account, AWS CLI, OpenAI key, or internet connection is required at runtime.

## Fresh-clone setup

PowerShell:

```powershell
py -3.11 -m pip install uv==0.11.16
uv sync --frozen --extra dev
Copy-Item .env.example .env
uv run prostate-journey --help
```

Linux/macOS:

```bash
python3.11 -m pip install uv==0.11.16
uv sync --frozen --extra dev
cp .env.example .env
uv run prostate-journey --help
```

`.env` is ignored by Git. The application does not load it itself; Docker Compose loads the
non-secret settings it needs and shell users may export selected variables. Never put a real secret
in `.env.example`.

## Quality gates

```powershell
uv lock --check
uv run python -m pip check
uv run ruff format --check src tests eda scripts
uv run ruff check src tests eda scripts
uv run mypy src
uv run pytest
uv run python scripts/check_no_secrets.py --root .
uv run python scripts/check_markdown_links.py --root .
uv run prostate-journey industry-check --allow-missing-release
```

`make check` runs the corresponding source gates where GNU Make is available.

## Analytical pipeline

Run the deterministic quick profile into mutable working paths:

```powershell
uv run prostate-journey run-all `
  --config configs/prostate_scenario_quick.yaml `
  --output-dir .test-work/local-gold `
  --report-dir .test-work/local-reports
```

The standard working locations are `data/gold/` and `data/reports/`. The CLI rejects mutable
outputs that overlap `data/releases/` or any directory carrying `IMMUTABLE_RELEASE`.

Create a candidate release only from a reviewed, clean commit and a never-used release name:

```powershell
uv run prostate-journey final-release `
  --config configs/prostate_scenario.yaml `
  --release-name BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1
```

Do not rerun this command against an existing release directory. The packager fails closed.

## Presentation generation

The presentation command resolves the newest complete accepted synthetic release and does not
silently fall back to `data/gold/`:

```powershell
uv run prostate-journey presentation-package
```

Output:

```text
outputs/presentation/<release-id>/
```

Scientific or predictive evidence enters the package only when its own sealed manifest matches the
same release and source identity.

## Local application

Verify all release and presentation hashes without starting a server:

```powershell
uv run prostate-journey application-check
```

Start the aggregate-only service:

```powershell
uv run prostate-journey serve
```

Open:

- frontend: `http://127.0.0.1:8080/`
- liveness: `http://127.0.0.1:8080/health`
- readiness: `http://127.0.0.1:8080/ready`

`/health` means the process is alive. `/ready` means one accepted immutable release and its exact
aggregate presentation package have resolved and passed integrity checks. OpenAI is never a
readiness dependency.

Stop with `Ctrl+C`. The process handles `SIGINT`/`SIGTERM`, stops accepting work, closes the socket,
and exits. Application startup and HTTP serving do not write to certified or presentation mounts.

## Docker

Build the locked non-root image:

```powershell
docker build --tag prostate-journey-analytics:local .
```

Start with release and presentation directories mounted read-only:

```powershell
docker compose up --build
```

Then open `http://127.0.0.1:8080/`. Inspect:

```powershell
docker compose ps
docker compose logs analytics-app
```

Stop cleanly:

```powershell
docker compose down
```

The image deliberately excludes `data/`, `outputs/`, `.env`, local virtual environments, and Git
history. Compose mounts only `data/releases/` and `outputs/presentation/`, both read-only.

## Output namespaces

| Trust level | Path | Mutability |
|---|---|---|
| Working analytical data | `data/gold/` | mutable and regenerable |
| Working reports | `data/reports/` | mutable and regenerable |
| Certified synthetic releases | `data/releases/` | append-only release directories; sealed artifacts immutable |
| QA summaries | `outputs/industry_readiness/` | mutable until captured in a release |
| Presentation packages | `outputs/presentation/` | regenerable, release-matched aggregate outputs |
| Temporary execution | `.test-work/runtime/` or container `/tmp` | disposable |
| Future experiments | `outputs/experiments/` | untrusted; never a certified input |

## Common failure modes

- `No complete certified analytical release`: create or mount an accepted synthetic release.
- `release manifest SHA-256 mismatch`: do not repair in place; investigate and restore the exact
  release from its approved archive.
- `Presentation artifact SHA-256 mismatch`: regenerate the presentation into a fresh reviewed
  package; do not suppress verification.
- `/health` is 200 and `/ready` is 503`: the process works, but required local artifacts are missing
  or invalid. Inspect the structured error category in `/ready` and logs.
- Legacy v2.1 warnings: historical artifacts can be demonstrated, but they are not the final v2.2
  Stage-4 candidate.

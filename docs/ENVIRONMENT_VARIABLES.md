# Environment-variable contract

No variable in this document contains a real credential. Local defaults are non-secret. The
application validates types and path boundaries in `prostate_journey.app_config`.

| Variable | Purpose | Requirement | Safe local default | Local use | Proposed AWS source |
|---|---|---|---|---|---|
| `PROSTATE_JOURNEY_CONFIG` | Analytical scenario YAML used by scripts | optional | `configs/prostate_scenario.yaml` | pipeline selection | task/job non-secret environment |
| `PROSTATE_JOURNEY_APP_CONFIG` | Base application YAML | optional | `configs/application.yaml` | service configuration | baked image path or task environment |
| `PROSTATE_JOURNEY_ENVIRONMENT_CONFIG` | Optional profile YAML | optional | `configs/environments/local.yaml` | profile override | baked reviewed profile |
| `PROSTATE_JOURNEY_ENVIRONMENT` | Environment label | optional | `local` | log and health context | ECS task environment, e.g. `dev` |
| `PROSTATE_JOURNEY_HOST` | HTTP bind interface | optional | `127.0.0.1` | loopback-only local service | `0.0.0.0` in the container |
| `PROSTATE_JOURNEY_PORT` | HTTP port | optional | `8080` | local/Compose port | ECS task definition, `8080` |
| `PROSTATE_JOURNEY_LOG_LEVEL` | Logging threshold | optional | `INFO` | local logs | ECS task environment |
| `PROSTATE_JOURNEY_LOG_FORMAT` | `json` or `text` | optional | `json` | structured local logs | `json` for CloudWatch ingestion |
| `PROSTATE_JOURNEY_WORKING_DATA_ROOT` | Mutable analytical output | optional | `data/gold` | local pipeline only | separate batch-job workspace; not web task |
| `PROSTATE_JOURNEY_WORKING_REPORT_ROOT` | Mutable report output | optional | `data/reports` | local pipeline only | separate batch-job workspace |
| `PROSTATE_JOURNEY_RELEASE_ROOT` | Immutable release namespace | optional | `data/releases` | readiness and presentation provenance | read-only materialized S3 release prefix |
| `PROSTATE_JOURNEY_QA_ROOT` | Non-release QA summaries | optional | `outputs/industry_readiness` | source checks | CI artifact location |
| `PROSTATE_JOURNEY_PRESENTATION_ROOT` | Aggregate package namespace | optional | `outputs/presentation` | files eligible for serving | read-only materialized S3 presentation prefix |
| `PROSTATE_JOURNEY_PRESENTATION_DIR` | Exact package override | optional | empty; release-matched path is derived | controlled troubleshooting | immutable selected release path |
| `PROSTATE_JOURNEY_TEMP_ROOT` | Disposable workspace | optional | `.test-work/runtime` | local temporary files | Fargate ephemeral storage `/tmp/prostate-journey` |
| `PROSTATE_JOURNEY_EXPERIMENT_ROOT` | Future untrusted experiment namespace | optional | `outputs/experiments` | reserved only | separate non-certified prefix, if approved |
| `PROSTATE_JOURNEY_VERIFY_RELEASE_HASHES` | Full startup integrity verification | optional | `true` | fail-closed startup/readiness | `true`; do not weaken silently |
| `PROSTATE_JOURNEY_READINESS_CACHE_SECONDS` | Maximum readiness cache period | optional | `30` | avoids hashing all artifacts per request | task environment, 0–300 seconds |
| `AI_ANALYSIS_STUDIO_ENABLED` | Start the separate optional AI Studio | optional | `true` in its local config | set `false` to disable all AI routes/assets | reviewed task environment flag |
| `AI_STUDIO_PROVIDER_ENABLED` | Permit configured OpenAI requests inside AI Studio | optional | `true` | set `false` for the provider-free demo while retaining deterministic tools | reviewed task environment flag |
| `AI_STUDIO_INTERACTIVE_RUN_TTL_DAYS` | Expiry boundary for run actions | optional | `7` | local experiment governance | reviewed retention configuration |
| `OPENAI_API_KEY` | Server-side credential for optional AI Studio only | optional; never used by standard Analytics | empty | ignored local `.env` after rotation | Secrets Manager only after approval |
| `OPENAI_VECTOR_STORE_ID` | Optional release-matched File Search store | optional | empty | ignored local `.env`; stale values fail closed | managed non-secret runtime reference |
| `AI_STUDIO_ACCESS_TOKEN` | Bearer gate required for non-loopback AI Studio | required outside local loopback | empty | do not expose frontend-side | Secrets Manager or identity bootstrap |

## Precedence

1. `configs/application.yaml`.
2. Selected `configs/environments/<environment>.yaml` profile.
3. Environment variables.
4. Explicit CLI overrides.

Analytical assumptions remain in versioned analytical YAML and contracts. Application variables do
not change cohort definitions, model targets, scientific estimands, or certified evidence.

## Secret rules

- Never commit `.env` or put real values in `.env.example`.
- Never pass a secret as a Docker build argument or copy it into an image layer.
- Never put secrets in HTML, JavaScript, manifests, test fixtures, command output, or logs.
- Standard Analytics performs no OpenAI call. The separate AI Studio calls OpenAI only for an
  explicitly configured Q&A, routing, planning, or optional narrative request; its deterministic
  presentation path and static fallback make no provider call.
- A future AWS deployment should reference Secrets Manager from the task definition, not store
  plaintext values in repository or CI variables. A rotated environment-injected secret requires a
  new task deployment before the process sees the new value.

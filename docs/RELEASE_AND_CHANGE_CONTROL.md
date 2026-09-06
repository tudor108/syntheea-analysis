# Release and change control

## Release classes

- Working build: explicit `data/gold`, never selected implicitly for stakeholder use.
- Candidate: immutable package that passed the repository's internal synthetic contract.
- Approved analytical release: future organizational state requiring named RWE, QA, privacy and
  security approvals; this repository currently has none.
- Production release: future deployment state with operational controls; currently not applicable.

## v2.2 candidate identity

The reserved identifier is:

```text
BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1
```

Its sole source is the clean commit recorded under `git.git_commit` in `release_manifest.json`.
No file may be copied into the sealed directory after release creation.

## Clean-clone setup and verification

Supported CPython versions are 3.11 and 3.13. The canonical dependency resolution is `uv.lock`.

```powershell
git clone <approved-repository-url> prostate-patient-journey-synthetic
cd prostate-patient-journey-synthetic
uv sync --frozen --extra dev --python 3.13
uv run ruff format --check src tests eda
uv run ruff check src tests eda
uv run mypy src
uv run pytest
uv run prostate-journey industry-check --allow-missing-release
```

Create a fresh full release from a clean commit (use a unique reproduction suffix if RC1 already
exists):

```powershell
uv run prostate-journey final-release `
  --config configs/prostate_scenario.yaml `
  --release-name BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1_REPRO
```

The command fails on a dirty tracked source, reused destination, failed quality gate, export
parity, DQ/reconciliation mismatch, non-100 internal scorecard or reproducibility mismatch.

## Promotion workflow

1. Open a reviewed change with linked requirement/risk and tests.
2. Pass CI on supported runtimes.
3. Select and record one commit; do not release a merge-in-progress or dirty tree.
4. Run `final-release` into a never-used directory.
5. Generate EDA and presentation only from that candidate analytical directory.
6. Run strict `industry-check` over release, EDA and presentation.
7. Independent QA verifies manifest/hash/checksum evidence and claim wording.
8. Record named approvals or retain candidate status.

## Change impact and versioning

| Change | Minimum version effect | Mandatory revalidation |
|---|---|---|
| Editorial docs with no claim/definition effect | patch | Links, claims and source gates |
| Bug fix or non-breaking output addition | patch | Full CI and affected analytical gates |
| Cohort, endpoint, censoring, persistence, market or model definition | minor | Full data regeneration, DQ, EDA, models, claims and SME review |
| Breaking schema or semantic contract | major | Consumer migration, full validation and approvals |
| Dependency/runtime update | patch/minor by impact | Clean environment, full tests and deterministic reproduction |

## Rollback and revocation

- Releases are never overwritten. Revoke by publishing a signed revocation record identifying the
  release ID, reason, owner, date and replacement; preserve evidence for audit.
- Frontends and reports must be removed from distribution if their manifest points to a revoked
  release.
- Rollback means promoting a previously verified immutable release, not rebuilding it under the
  same ID.
- Security/privacy incidents follow the future organizational incident process; none is implied by
  this local repository.

## Generated artifact policy

See [generated artifact policy](GENERATED_ARTIFACT_POLICY.md). Git stores source, contracts and
documentation; release storage or an approved artifact registry stores immutable generated data.

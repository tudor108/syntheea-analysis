# Deployment contract

This contract distinguishes the implemented local application from a future AWS deployment. AWS is
not deployed and real patient data is blocked.

## Current local implementation

| Contract item | Value |
|---|---|
| Image | `prostate-journey-analytics:local`, built from `Dockerfile` |
| Runtime | CPython 3.11.9 slim, dependencies from frozen `uv.lock` |
| User | UID/GID `10001:10001`, no shell/home requirement |
| Command | `prostate-journey serve` |
| Port | container `8080`; Compose publishes loopback only |
| Liveness | `GET /health`; process-alive check, independent of release/OpenAI |
| Readiness | `GET /ready`; verifies accepted release, immutable marker, checksums, aggregate presentation manifest and file hashes |
| Frontend | `GET /` redirects to `/executive_story.html`; only manifest-listed files are served |
| Startup | hashes mounted artifacts, records readiness, then binds HTTP even if not ready |
| Shutdown | handles `SIGINT` and `SIGTERM`; closes server; Compose grace period 15 seconds |
| Logging | one JSON object per line to stdout/stderr |
| Secrets | none required; `OPENAI_API_KEY` is optional, masked by the typed model, and unused |
| Release filesystem | `/app/data/releases`, required for ready state, read-only |
| Presentation filesystem | `/app/outputs/presentation`, required for ready state, read-only |
| Temporary filesystem | `/tmp`, 64 MiB tmpfs in Compose; application currently writes no runtime state |
| Persistence | certified/presentation artifacts persist outside the container; no mutable application database |
| Outbound network | none for the current application process |
| Authentication | none locally; bind defaults to `127.0.0.1` |

Structured log fields are `timestamp`, `level`, `logger`, `message`, `run_id`, `release_id`,
`operation`, `status`, `duration_ms`, and `error_category`. Do not add secrets, raw records, or
patient-level payloads.

## Proposed AWS deployment

| Contract item | Proposed value requiring AWS-owner approval |
|---|---|
| Image identity | ECR image by immutable SHA-256 digest; commit tag is descriptive only |
| Platform | one ECS service on Fargate; no Kubernetes |
| Initial task size | 0.5 vCPU and 1 GiB memory; confirm with load test before pilot |
| Desired count | 2 tasks for availability after non-production smoke; 1 is acceptable for cost-limited development |
| Container port | `8080/tcp` |
| Container health | task-definition command calls `GET /health` |
| Traffic readiness | ALB target health calls `GET /ready`; do not route a task returning 503 |
| Ingress | HTTPS only through ALB and approved identity/control layer |
| Artifact source | exact versioned S3 `releases/<release-id>` and `presentations/<release-id>` prefixes |
| Artifact materialization | one-shot task container copies approved objects to a shared ephemeral volume before app startup |
| Main task IAM role | no AWS permissions for current application; separate role if later justified |
| Init task IAM | read-only `s3:GetObject`/version access to one selected release and presentation prefix plus required KMS decrypt |
| Execution role | ECR pull, `awslogs`, and task-definition secret resolution only |
| Logs | CloudWatch log group with approved retention, KMS policy, alarms, and access control |
| Secrets | Secrets Manager references in task definition; no plaintext task environment or image layer |
| Temporary storage | Fargate ephemeral volume sized after measuring selected artifacts; no hidden persistence |
| Static delivery | optional private S3 + CloudFront OAC when static-only mode is selected |
| Authentication | approved enterprise IdP preferred; Cognito only if it fits the enterprise identity decision |
| Outbound internet | none for main container; S3/KMS endpoints for artifact init; other egress denied by default |

The proposed artifact-init mechanism is a deployment responsibility and is not implemented as an
AWS client in this repository. The AWS engineer must pin that helper image by digest and record its
software inventory.

## Startup contract

1. Required read-only artifact paths are materialized or mounted.
2. Main container starts and `/health` returns 200.
3. It resolves the newest accepted release, or the exact configured presentation path.
4. It verifies release marker, manifest identity, separate archive sizes/hashes, complete checksum
   inventory, aggregate-only presentation status, source-release alignment, and presentation hashes.
5. `/ready` returns 200 only after all checks pass. An error returns 503 without serving untrusted
   static files.

The default readiness cache is 30 seconds. A deployment may lower it after measuring hash cost but
must not disable startup hash verification.

## Deployment smoke tests

Run from an approved network after deployment:

```text
GET /health                    -> 200, status=ok, synthetic_data_only=true
GET /ready                     -> 200, status=ready, expected release_id
GET /                           -> 302 to /executive_story.html
GET /executive_story.html      -> 200, synthetic disclaimer visible
GET /presentation_manifest.json -> 404 because it is not on the serve allow-list
GET /../release_manifest.json  -> 400/404; no path escape
```

Also compare the deployed ECR digest, release manifest hash, presentation manifest hash, and selected
S3 object version IDs with the approved deployment record. Confirm no OpenAI call and no unexpected
outbound connection occurs.

## Rollback criteria

Rollback to the last approved image digest and artifact version if any of the following occurs:

- `/health` or `/ready` fails after the configured deployment grace period;
- release or presentation hash mismatch;
- selected release ID differs from the change record;
- security, secret, or access-control regression;
- synthetic disclaimer or provenance disappears;
- frontend smoke/accessibility gate regresses;
- error rate, startup duration, memory, or latency exceeds the approved threshold;
- any indication of real patient data entering the synthetic environment.

Never repair an immutable release in place. Select the prior immutable version and investigate the
failed version under incident/change control.

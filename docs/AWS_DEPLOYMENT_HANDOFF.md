# AWS deployment handoff — for the future AWS engineer

> **Nothing in this handoff has been deployed.** Do not execute cloud changes until the account,
> Region, budget, identity, security, and synthetic-only scope are approved.

Read first:

- [AWS target architecture](AWS_TARGET_ARCHITECTURE.md)
- [Deployment contract](DEPLOYMENT_CONTRACT.md)
- [Environment variables](ENVIRONMENT_VARIABLES.md)
- [AWS security checklist](AWS_SECURITY_CHECKLIST.md)
- [Real-data readiness checklist](REAL_DATA_READINESS_CHECKLIST.md)

## Required decisions before implementation

Obtain written values/owners for:

- AWS Organization/account IDs for development and any later production environment;
- approved Region and residency rationale;
- platform owner, security owner, privacy owner, FinOps owner, and application owner;
- monthly budget, alarms, tagging standard, log retention, and KMS ownership;
- enterprise identity integration and intended user groups;
- whether the pilot uses static-only CloudFront/S3 or the ECS application mode;
- release ID, presentation package ID, source commit, image digest, and promotion approver;
- retention/Object Lock policy and break-glass process;
- private-only versus controlled external ingress.

## Build and promotion inputs

The deployer receives exactly:

| Input | Acceptance evidence |
|---|---|
| reviewed source commit | protected-branch review and CI PASS |
| container image | `Dockerfile`, frozen lock, SBOM, vulnerability result, immutable digest |
| certified synthetic release | `release_manifest.json`, `IMMUTABLE_RELEASE`, `CHECKSUMS.sha256`, two archives |
| aggregate presentation | `presentation_manifest.json`, manifest-listed files only, `patient_level_data_included=false` |
| configuration | non-secret environment values and exact selected release ID |
| approvals | change record, security/platform owner, data classification `synthetic` |

Reject mixed release IDs, mutable tags without digest resolution, unlisted presentation files,
working `data/gold`, and anything under `outputs/experiments`.

## Ordered deployment work

1. Create or select the approved AWS account and Region under organizational controls.
2. Define infrastructure through the organization's reviewed IaC standard. This repository does not
   include account-specific IaC because account, Region, identity, and policy inputs are not approved.
3. Create a private ECR repository with immutable tags and registry-level scanning. Deploy by digest,
   not by a movable tag. AWS documents immutable tag behavior and registry scan configuration here:
   [ECR tag immutability](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html).
4. Create a private, encrypted, versioned S3 artifact bucket. Separate release, presentation, and
   experiment prefixes with IAM and bucket-policy controls. Decide Object Lock before promotion.
5. Upload one exact release and presentation package, preserving relative paths and recording object
   version IDs. Independently recheck repository hashes before promotion.
6. Create separate build/deploy, task-execution, artifact-init, and runtime roles. The current main
   application role should have no AWS API permissions.
7. Create CloudWatch log group, retention, encryption/access policy, alarms, and dashboards.
8. Create VPC/subnets/security groups/endpoints according to the approved ingress mode. Permit port
   8080 to tasks only from the ALB security group.
9. Register a Fargate task definition by immutable image digest. Configure the one-shot artifact
   container, shared task volume, dependency-on-success, read-only main mount, read-only root
   filesystem, non-root user, dropped capabilities, JSON logs, CPU/memory, and health command.
10. Create ECS service and ALB target group. Use `/ready` for traffic health and `/health` for
    container liveness. ECS only honors task-definition health checks for task health:
    [ECS health checks](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/healthcheck.html).
11. Add HTTPS certificate, approved authentication, access logging, and optional CloudFront. For a
    direct static S3 origin, use CloudFront OAC with always-signed requests.
12. Run all smoke tests in the [deployment contract](DEPLOYMENT_CONTRACT.md), retain outputs, and
    obtain the change approver's GO before user access.

## Required task-definition values

- command: `prostate-journey serve`
- application port: `8080`
- user: `10001:10001`
- root filesystem: read-only
- environment: non-secret variables from [environment contract](ENVIRONMENT_VARIABLES.md)
- secret references: none today; future optional values from Secrets Manager only
- volume targets: `/app/data/releases` and `/app/outputs/presentation`, read-only in main container
- temporary storage: writable `/tmp`, explicitly sized
- liveness command: standard-library Python GET to `http://127.0.0.1:8080/health`
- target-group readiness: `GET /ready`, expected HTTP 200
- stop timeout: at least 15 seconds
- logs: stdout/stderr through `awslogs`

AWS supports Secrets Manager references through the ECS task-definition `secrets` field. If a later
feature introduces a secret, grant only the execution permissions for that exact ARN and redeploy
tasks after rotation:
[ECS secret injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html).

## Evidence to return to the application owner

- reviewed IaC plan and apply record;
- account/Region/environment identifiers;
- ECR repository, image digest, scan result, and SBOM;
- S3 bucket/prefix, object version IDs, manifest hashes, encryption and retention settings;
- IAM role/policy review with access-analyzer evidence;
- ECS task definition revision and service configuration;
- ALB/CloudFront/authentication configuration and access-log destinations;
- CloudWatch log/metric/alarm evidence;
- smoke-test output and release ID shown by `/ready`;
- rollback target and rollback test;
- cost estimate, budget, and alarm evidence;
- explicit confirmation that only synthetic data was used.

## Stop conditions

Do not continue if artifacts fail a hash, a requested permission exceeds the documented role, the
release identity is ambiguous, public access is broader than approved, the image scan has an
unaccepted critical finding, the budget is absent, or any real patient data is proposed.

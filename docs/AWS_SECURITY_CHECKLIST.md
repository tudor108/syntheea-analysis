# AWS security handoff checklist — proposed environment

No item below is currently implemented in AWS. Evidence must come from the future AWS owner.

## Identity and separation of duties

- [ ] Separate human build/deploy access from ECS task execution and runtime roles.
- [ ] Use federated enterprise identities and short-lived sessions; no long-lived access keys.
- [ ] Grant the main application no AWS API permission unless a reviewed need is demonstrated.
- [ ] Scope artifact-init access to the exact S3 release/presentation prefixes and required KMS key.
- [ ] Restrict `iam:PassRole` to approved deployment automation and exact roles.
- [ ] Enable MFA/break-glass controls and retain access-review evidence.

## Secrets and cryptography

- [ ] Keep current secret set empty; OpenAI is not required.
- [ ] If a later approved service needs a secret, store it in Secrets Manager and reference its ARN.
- [ ] Encrypt ECR, S3, CloudWatch Logs, and Secrets Manager with approved key ownership/policies.
- [ ] Enforce TLS for ingress and service/origin communication.
- [ ] Prohibit secrets in task plaintext environment, image layers, CI logs, HTML, JavaScript, and S3
      presentation files.

## Network and access

- [ ] Put Fargate tasks in private subnets.
- [ ] Allow task port 8080 only from the ALB security group.
- [ ] Limit ALB ingress to approved networks/users and HTTPS.
- [ ] Block all S3 public access; use bucket policy and CloudFront OAC if static delivery is enabled.
- [ ] Review VPC endpoints and default-deny egress against cost and operational requirements.
- [ ] Enable ALB/CloudFront/S3 access logs with approved retention and access controls.

## Supply chain and containers

- [ ] Build from the reviewed commit and frozen lockfile.
- [ ] Generate an SBOM and retain it with the deployment record.
- [ ] Scan dependencies and image; document disposition for every critical/high finding.
- [ ] Enable ECR registry scanning and immutable tags; deploy only an image digest.
- [ ] Run as UID 10001, read-only root, dropped Linux capabilities, no privilege escalation.
- [ ] Pin any artifact-init helper image by digest and scan it independently.

## Audit, detection, response, and cost

- [ ] Enable organization-approved CloudTrail, configuration monitoring, and alert routing.
- [ ] Send JSON task logs to CloudWatch and alarm on readiness failures, restarts, 5xx, and access
      anomalies without logging raw records or secrets.
- [ ] Record release ID, object version IDs, source commit, image digest, task revision, and approver.
- [ ] Define incident severity, evidence preservation, owner, communication, containment, and
      rollback procedure.
- [ ] Define backup/restore for S3 versioned artifacts and test rollback to the prior immutable set.
- [ ] Configure mandatory tags, cost allocation, budget, forecast, and anomaly alerts before service
      creation.
- [ ] Separate development and any later production account/environment.

## REAL PATIENT DATA — BLOCKED

No real patient data may be uploaded, processed, logged, queried, cached, or presented until every
approval and control in [REAL_DATA_READINESS_CHECKLIST.md](REAL_DATA_READINESS_CHECKLIST.md) is
complete and independently evidenced. Synthetic readiness is not privacy, security, clinical, RWE,
or production approval.

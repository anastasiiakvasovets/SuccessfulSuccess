# ADR 0007: Manage auth, reports and ai with Terraform in HCP Terraform

- **Status:** Accepted
- **Date:** 2026-10-29
- **Lab:** 7 (record of the import: [docs/migration/](../migration/inventory.md))

## Context

Six CloudFormation stacks, each deployed by a `make` target from a laptop with the IAM user's keys.
Nothing showed what a deploy would change before it ran. More is coming that CloudFormation
handles badly: the **Google OAuth client** lives in Google Cloud (CloudFormation cannot manage it),
there will be **more environments** (dev, then staging/prod), and a **white-label** variant would
repeat the whole setup per customer with different domains and identity providers.

## Decision

- **Terraform**, state and runs in **HCP Terraform** (organization `ooad-nastyakvasovets`,
  workspace `successfulsuccess-dev`, `cloud {}` in `infra/versions.tf`).
- **Scope:** `auth`, `reports` and `ai` move (`infra/auth.tf`, `reports.tf`, `ai.tf`; the three
  templates are deleted). `ecr`, `backend` (API, RDS, network) and `frontend` (S3, CloudFront) stay in
  CloudFormation: they hold the data and the site, and moving them adds risk without a benefit yet.
  Terraform reads them with `data "aws_cloudformation_stack"` and `data "aws_lambda_function"`; they
  never read Terraform.
- **Who changes infrastructure:** whoever can push to `main`. A push starts a run in HCP Terraform:
  plan, then apply, with AWS credentials from the OIDC role `hcp-terraform-ooad-nastyakvasovets`
  (no stored keys). Locally there is only `make infra-plan` (and `infra-fmt`, `infra-validate`); no
  make target runs `terraform apply`.
- **Code is not Terraform's job.** Every `lifecycle { ignore_changes }`:

  | Resource | Ignored | Why |
  | --- | --- | --- |
  | `aws_lambda_function.builder`, `.parser` | `image_uri`, `publish` | `make aws-update-workers` (also run by `aws-deploy-backend`) pins the pushed image by digest; Terraform only sets `<repo>:latest` if it ever creates a function from scratch. Versions are never published. |
  | `aws_lambda_function.mailer` | `filename`, `source_code_hash`, `publish` | The zip is built from `infra/lambda/report_mailer/` only for a create; a code change goes out by hand, so a re-zip on another machine never shows as a diff. |

## Alternatives

- **CloudFormation** (status quo): no Google provider, change sets are per stack and rarely read,
  and a second environment means copying parameters by hand.
- **CDK:** better code reuse, but still CloudFormation underneath: same AWS-only limit, plus a
  language runtime and a synth step.
- **OpenTofu:** same language and providers. HCP Terraform (free tier, remote state, VCS runs,
  OIDC to AWS) was the deciding factor; switching later is cheap.
- One tool for AWS, Google and anything else is the main reason for Terraform over both AWS tools.

## Consequences

- **Secrets** (`google_client_secret`, `db_password`) and the personal emails (`sender_email`,
  `report_recipient`) are HCP workspace variables (secrets marked Sensitive). They end up in **AWS**
  (Cognito, the builder's `DATABASE_URL`, the mailer's env) and in the **state in plain text** (also
  the Google secret read back by the import). Anyone with read-state access to the workspace in HCP
  Terraform can read them: keep that to the organization's owners. Locally they exist only in
  `infra/secrets.auto.tfvars`, which is gitignored and in `infra/.terraformignore`.
- **The OIDC role is broad:** it trusts every workspace and run phase of the organization and has
  `AdministratorAccess`. Follow-up: limit the trust to `workspace:successfulsuccess-dev` and the
  policy to the services in scope.
- **If HCP Terraform is down:** nothing running breaks, only changes wait. The current state can be
  downloaded (Workspace → States → a state version, or the API). In an emergency, switch the workspace
  to execution mode **Local**, apply with your own credentials, then switch back and run a plan in
  HCP Terraform to confirm it shows no changes before anyone else applies.
- **Migration (one-time):** the old stacks were deleted with `DeletionPolicy: Retain`, then
  **26 resources were imported** (auth 5, reports 15, ai 6). **14 child resources were re-created**:
  inline IAM policies, managed-policy attachments, and the reports bucket's public-access block,
  ownership, encryption, lifecycle and notification. That was safe because each is a PUT of the
  whole document by name: writing the same content over what is already there changes nothing.
  The first apply: 26 imported, 14 added, 18 changed in place, **0 destroyed**; the next plan
  showed no changes (`docs/migration/plan-no-changes.txt`).
- Two config fixes kept the apply non-destructive: **`generate_secret` is left out** of the Cognito
  app client (import cannot read it back, and setting it, even to `false`, forces a new client and
  so a new client id that the API, the parser and the frontend build all check); and
  **`max_message_size = 1048576`** on both queues (SQS's current default; the provider's 256 KiB
  default would have shrunk them).
- A new CloudFront domain needs a Terraform run: Cognito's callback URLs and the parser's CORS are
  built from the frontend stack's output.

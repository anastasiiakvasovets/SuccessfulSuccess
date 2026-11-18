# ADR 0008: Run Spry's core on Google Cloud

- **Status:** Proposed
- **Date:** 2026-11-18
- **Lab:** 9 (findings: [docs/lab9-notes.md](../lab9-notes.md))

## Context

Spry's core runs on AWS:

- the Next.js static export in S3 behind CloudFront;
- the FastAPI API in a Lambda container behind a function URL (through Mangum);
- **PostgreSQL 16 on RDS, `db.t3.micro`**, private, in the default VPC.

It is not Aurora: the descriptions in `infra/backend.yml` and `.env.example` still say "Aurora
Serverless v2 … pauses when idle". That is stale since commit `c0307bd`. The resource is an
`AWS::RDS::DBInstance`, and it never pauses: it bills every hour.

These three parts are **CloudFormation** stacks (`infra/ecr.yml`, `backend.yml`, `frontend.yml`).
Terraform in HCP Terraform (ADR 0007) covers only sign-in (`auth.tf`, Cognito), the weekly report
(`reports.tf`: EventBridge Scheduler → SQS → Lambda → S3 → Lambda → SES) and the agenda parser
(`ai.tf`: Lambda, Claude API).

Lab 9 moves the core (frontend, API, database) to Google Cloud, project `spry-kvasovets-2026`.
The region is **`us-central1`** for Cloud Run, Cloud SQL and Artifact Registry. What stays on AWS
is in `us-east-1`. What the code allows:

- The API is a plain ASGI app, and `backend/Dockerfile` already runs it with uvicorn. Only
  `app/lambda_handler.py` and `Dockerfile.lambda` are Lambda-specific.
- The database is reached through one variable, `DATABASE_URL` (SQLAlchemy async + asyncpg).
  Alembic reads the same one, and Cloud SQL's Unix socket fits that URL with no code change.
- Every business route is under `/api/v1`. One hosting rewrite (`/api/**`) can therefore put the
  API on the site's origin: the frontend calls relative URLs (`NEXT_PUBLIC_API_BASE_URL=""`) and
  needs no CORS.
- The API refuses every `/api/v1/*` request without a Cognito pool (503) or a valid Cognito access
  token (401). `meetings.owner_id` is the Cognito `sub`.
- On AWS the database password sits in plain text inside the Lambda's `DATABASE_URL` env var.

## Decision

### Component map

| AWS today | GCP counterpart | Decision | Why |
| --- | --- | --- | --- |
| S3 + CloudFront (+ CloudFront Function for `index.html`) | Firebase Hosting | **replace** | Serves `frontend/out/` as is, and directory index needs no function. A `/api/**` rewrite to Cloud Run puts the API on the same origin. |
| Lambda + function URL (Mangum) | Cloud Run (`us-central1`) | **replace** | Runs the existing `backend/Dockerfile` (uvicorn, `--port 8000`) and scales to zero. `allUsers` invoker, because the app checks tokens itself. |
| Direct invokes `{"action": "migrate"}` / `show-agendas` | Cloud Run Jobs | **replace** | `alembic upgrade head` as a job with the same image. See [Database](#database). |
| ECR | Artifact Registry (`us-central1`, Docker) | **replace** | Same image, built for `linux/amd64`, deployed by digest as today. |
| RDS PostgreSQL 16 `db.t3.micro` (the lab text and `backend.yml`'s description say Aurora Serverless v2) | Cloud SQL for PostgreSQL 16 (`us-central1`) | **replace** | Same engine: JSONB, `timestamptz` and the Alembic migrations work unchanged. See [Database](#database). |
| VPC, security groups (function ↔ DB) | Cloud SQL Unix socket + `roles/cloudsql.client` | **replace** | No VPC to manage. DB access is an IAM role on the API's service account. |
| DynamoDB | Firestore | **N/A** | Spry uses no DynamoDB. |
| Cognito (+ Google IdP) | Identity Platform | **keep on AWS** | Multi-cloud: Cloud Run verifies Cognito tokens against the pool's public JWKS. Identity Platform is deferred. See [What we don't move (yet)](#what-we-dont-move-yet). |
| EventBridge Scheduler | Cloud Scheduler | **keep on AWS** | Part of the weekly report, which stays. |
| SQS (+ DLQ) | Pub/Sub / Cloud Tasks | **keep on AWS** | Part of the weekly report, which stays. |
| S3 reports bucket | Cloud Storage | **keep on AWS** | Part of the weekly report, which stays. |
| SES | none from Google | **keep on AWS** | See [E-mail](#e-mail). |
| Bedrock (blocked for the account; the parser uses the Claude API) | Vertex AI (Claude models) | **keep on AWS** | The parser stays. Vertex AI is the path when it moves (ADR 0006: the model is a setting). |
| Plain-text `DATABASE_URL` in the Lambda config; SSM Parameter Store for the Claude API key; no Secrets Manager | Secret Manager | **replace** for the core | The whole `DATABASE_URL` becomes one secret, mounted with `--set-secrets`. The parser's key stays in SSM. |
| CloudWatch Logs | Cloud Logging | **replace** for the core | Cloud Run sends stdout to Cloud Logging without configuration. |
| IAM roles | Service accounts | **replace** for the core | See [Identity & access](#identity--access). |
| CloudFormation (`ecr`, `backend`, `frontend`) | Terraform, `google` provider, in `gcp/` | **replace** | A separate root module `gcp/`, HCP Terraform workspace **`spry-gcp`** in organization `ooad-nastyakvasovets`. It is separate from `infra/` (`successfulsuccess-dev`), so the AWS and GCP states, credentials and runs never mix. The three stacks are deleted after cutover. |
| Terraform `aws` (`infra/`: auth, reports, ai) | — | **keep** | Still manages what stays on AWS, plus the cross-cloud changes below. |

### Database

All four options compared with the baseline: RDS `db.t3.micro` does not pause either, so "always
on" is what we pay for today.

| Option | Latency | Monthly bill | Code |
| --- | --- | --- | --- |
| **A. Cloud SQL `db-f1-micro`, 24/7** | Same region as Cloud Run (`us-central1`), Unix socket: about 1 ms per query. | $0.0105/h × 730 h ≈ **$7.67** + 10 GB SSD **$1.70** ≈ **$9.37** | None: a new `DATABASE_URL`. |
| **B. Cloud SQL `db-f1-micro`, stopped when not in use** | As A while running. A stopped instance takes minutes to start, and requests get 503 meanwhile (`/health` reports it). | Compute only for running hours, e.g. 120 h ≈ $1.26. **Storage $1.70 is billed while stopped too.** About **$3** at 120 h. | None. Add `make gcp-db-start` / `gcp-db-stop` (activation policy), optionally a Cloud Scheduler stop at night. |
| **C. Firestore** | Low, but more round trips per request (no joins: meeting, participants and user are separate reads). | **$0** within the daily free quota (50k reads, 20k writes, 1 GiB). | **Rewrite**: repositories, SQLAlchemy models, Alembic, the agenda JSONB writes, and the report builder's SQL aggregations. |
| **D. Keep RDS on AWS, query it cross-cloud** | One `us-central1` ↔ `us-east-1` round trip per query, roughly 20–30 ms each. A request runs several queries, so this adds tens of ms per request instead of ~1 ms per query. | The RDS bill stays as is (it never pauses). Add AWS egress ($0.09/GB) and either a site-to-site VPN (hourly on both sides) or a public RDS endpoint with a static Cloud Run egress IP (Cloud NAT, hourly). | Little code. But RDS is private (`PubliclyAccessible: false`) and must be exposed: the password crosses the internet, and TLS is required. |

**Decision: B.** Cloud SQL for PostgreSQL 16, `db-f1-micro`, 10 GB SSD, in `us-central1`, the
same region as Cloud Run. It is stopped when nobody uses it and started before a session or demo.
- A needs no discipline, but at lab usage it costs about three times as much.
- C is a rewrite to save $3–9.
- D keeps AWS in every request and adds egress and a second network to secure.

- **Connection string.** The whole URL is one Secret Manager secret, read by the service and the
  migration job:
  `postgresql+asyncpg://app:<pass>@/meetings?host=/cloudsql/spry-kvasovets-2026:us-central1:spry-db`
  (secret `spry-database-url`). Cloud Run mounts the socket (a `cloud_sql_instance` volume at
  `/cloudsql`). Terraform generates the password from `[A-Za-z0-9]` only, so the URL needs no
  escaping. A second secret, `spry-db-password`, holds the bare password for people connecting
  through the Cloud SQL Auth Proxy. `spry-api@` cannot read it.
- **Migrations.** A Cloud Run Job runs `alembic upgrade head` with the service's image and
  service account. The service runs with `RUN_MIGRATIONS_ON_START=false`, so instances starting
  together never race. The first deploy may instead leave it `true` with `--max-instances 1`.
- **Data.** We start from an **empty Cloud SQL database**: Alembic creates the schema, and
  `python -m app.seed <cognito-sub>` adds demo meetings (`app.reports.seed_weeks` if report data is
  wanted). No data is copied from RDS. It is private, so `pg_dump` would need a bastion or a
  temporarily public instance, which is not worth it for the lab. Cognito stays, so the seeded
  `owner_id` values are real users' `sub`s.
- **Connections.** `db-f1-micro` is shared-core with no SLA and allows ~25 connections. Each Cloud
  Run instance can open up to 15 (SQLAlchemy's default pool 5 + 10), so the service gets
  `--max-instances 2`, or the pool size moves into `Settings`.

### E-mail

Google Cloud has no e-mail sending service. **Decision: keep SES** (multi-cloud). Only the
weekly report's mailer sends mail, and it stays on AWS (below). The API on Cloud Run sends none
today, so nothing on GCP calls SES in this iteration.

If GCP code has to send mail later, the alternative is **SendGrid or Mailgun** over HTTPS:
- the API key goes in Secret Manager;
- only the API's service account gets `roles/secretmanager.secretAccessor`, on that one secret;
- the key never goes in an env var, a file or the Terraform state.

### What we don't move (yet)

| Stays on AWS | Why | What the move requires now |
| --- | --- | --- |
| **Sign-in (Cognito + Google IdP)** | Multi-cloud on purpose. Every `meetings.owner_id` is a Cognito `sub`, and Cloud Run can fetch the pool's public JWKS (`https://cognito-idp.us-east-1.amazonaws.com/<pool>/.well-known/jwks.json`) itself. Unlike the VPC Lambda, it needs no `COGNITO_JWKS`. | Add `https://spry-kvasovets-2026.web.app` and `https://spry-kvasovets-2026.firebaseapp.com` to the app client's callback (`<origin>/auth/callback/`) and logout (`<origin>/`) URLs. Today `local.site_origins` in `infra/versions.tf` is only CloudFront + localhost. Change it in `infra/` and push to `main` (HCP Terraform applies). The service gets `COGNITO_REGION=us-east-1`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`; the frontend build gets the same `NEXT_PUBLIC_COGNITO_*` as today. |
| **Weekly report** (Scheduler, SQS, builder, S3, mailer, SES) | Five services and two Lambdas, and it depends on SES, which has no Google counterpart. It is not on the request path. | Nothing for the move itself, but **the builder reads RDS**. See [Consequences](#consequences). |
| **Agenda parser** | Depends on Bedrock / the Claude API and has no database access. Saving goes through the API, so saved agendas land in Cloud SQL. Moving it is a separate model-provider change (Vertex AI). | Add both Firebase origins to its function URL CORS (`infra/ai.tf`, also from `local.site_origins`), or build the frontend with `NEXT_PUBLIC_PARSER_URL=""` to hide the feature. |
| **Google OAuth client** | Already in Google Cloud; Cognito uses it. | Nothing. |

### Identity & access

- **Two service accounts.**
  - `terraform@` creates and changes infrastructure.
  - `spry-api@` is the identity Cloud Run and the migration job run as.

  Neither is the default compute account.
- **Least privilege, no basic roles.** No Owner or Editor anywhere.
  - `spry-api@`: `roles/cloudsql.client`, and `roles/secretmanager.secretAccessor` granted on the
    `DATABASE_URL` secret only (not project-wide). Log writing is built in.
  - `terraform@`:
    - the admin roles of the services in scope only: `run.admin`, `cloudsql.admin`,
      `artifactregistry.admin`, `secretmanager.admin`, `serviceusage.serviceUsageAdmin`
      (Firebase Hosting and Cloud Scheduler admin are added together with their resources);
    - `iam.serviceAccountAdmin` to manage the two service accounts;
    - `roles/iam.serviceAccountUser` on `spry-api@` only;
    - `resourcemanager.projectIamAdmin`, because Terraform manages the project bindings. An IAM
      condition (`modifiedGrantsByRole`) limits it to the roles listed in `gcp/iam.tf`, so it
      cannot grant Owner.

    The list lives in `gcp/iam.tf`, so a plan shows any change.
- **No service-account keys.** Key creation is blocked by the org policy
  `iam.disableServiceAccountKeyCreation` where the project allows it, and never done otherwise.
  - **Locally:** Terraform in `gcp/` runs with the owner's Application Default Credentials
    (`gcloud auth application-default login`), without impersonation. Impersonating `terraform@`
    (it needs `roles/iam.serviceAccountTokenCreator` for the owner's user) is an optional
    improvement, not a requirement: plans would then run with exactly the roles above. As in
    `infra/`, no make target applies.
  - **HCP Terraform (`spry-gcp`):** Workload Identity Federation. A pool with an OIDC provider for
    `app.terraform.io`, with an attribute condition that pins the organization
    `ooad-nastyakvasovets` **and** the workspace `spry-gcp`. That closes, on the GCP side, the gap
    ADR 0007 left open on the AWS side. The workspace sets `TFC_GCP_PROVIDER_AUTH=true`,
    `TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL`, `TFC_GCP_WORKLOAD_PROVIDER_NAME`.

    Lab 9 iteration: local execution with owner's ADC; WIF is the target for remote runs.
- Cloud Run allows unauthenticated invocation (`allUsers` → `roles/run.invoker`), as the Lambda URL
  does (`AuthType: NONE`). Firebase Hosting's rewrite needs it, and the app checks Cognito tokens on
  every `/api/v1` request.

## Alternatives

- **Identity Platform instead of Cognito.** Deferred, not rejected. It would put sign-in in the same
  cloud as the core, but it needs:
  - rewriting the frontend's auth (Amplify → Firebase Auth SDK in `lib/auth.ts`,
    `auth-provider.tsx`, `auth-page.tsx`, `login-redirect.tsx`);
  - rewriting the backend's `CognitoVerifier` (issuer `https://securetoken.google.com/<project>`,
    audience = project id, Google's keys);
  - re-creating the Google IdP;
  - **migrating every `owner_id`** from Cognito `sub` to Identity Platform uid.

  None of that is needed to run the core on GCP.
- **Move everything at once** (sign-in, report, parser): a user remap, a mail provider and a model
  provider change in one step, for no gain to the core.
- **Copy the data from RDS:** see [Database](#database), not worth a bastion for a lab.
- **GKE or Compute Engine instead of Cloud Run:** always-on cost and cluster/VM upkeep for one
  stateless container.
- **Cloud Run serving the frontend too** (Next.js `standalone`): a running server for files that are
  static today.
- **GCP resources inside `infra/`** (one workspace for both clouds): one plan would need AWS and GCP
  credentials at once, and a mistake in one cloud could block changes in the other.

## Consequences

**Gained**

- The core needs no VPC, NAT or security groups: the DB is reached through IAM and a socket.
- `DATABASE_URL` and its password leave the plain-text function config for Secret Manager, readable
  only by `spry-api@`.
- One origin for site and API: no CORS on the request path, and no API URL baked in per environment.
- The API container is the same image locally (compose) and in production. `Dockerfile.lambda` and
  Mangum are needed only while the AWS workers live.
- Keyless access everywhere, with the HCP trust for GCP narrowed to one workspace.

**Lost or at risk**

- **No auto-pause, and a risk of forgetting.** RDS never paused and neither does Cloud SQL, but
  option B depends on stopping it by hand (or a schedule). Forgetting costs the full
  ~$9.37/month. The `monthly-5usd` budget covers AWS only, so a **GCP budget alert** is needed too.
  A stopped instance makes the app answer 503 until it is started, which takes minutes.
- **The weekly report reads the old RDS.** After cutover the builder still queries RDS, so it would
  mail a report about data nobody updates any more. RDS must also stay up and billed for it. Options:
  1. **Disable it at cutover** (recommended): set the schedule's state to `DISABLED` in `infra/`,
     keep the code and queues, then delete the `backend` stack (and RDS) once nothing reads it.
     **Not done yet:** the schedule stays enabled until the cutover to GCP actually happens.
  2. **Move it later**: Cloud Scheduler → Cloud Run Job (same image, `app.reports` against Cloud
     SQL), mail still through SES, or SendGrid / Mailgun (see [E-mail](#e-mail)). This is a
     follow-up ADR.
  3. Point the AWS builder at Cloud SQL cross-cloud: rejected for the same reasons as option D.
- **Two clouds to run.** Two consoles, bills and sets of credentials (two HCP workspaces), plus
  cross-cloud configuration: Cognito callback / logout URLs and parser CORS must list the Firebase
  origins. An AWS outage breaks sign-in, and a GCP outage breaks the app.
- **Fresh data.** Meetings created on AWS are not carried over. Users sign in with the same Cognito
  accounts and start with an empty list (or seeded demo meetings).
- **Lock-in shifts, it does not end.** Firebase Hosting rewrites, Cloud SQL socket naming, Cloud Run
  service config and Workload Identity are GCP-specific. The app code stays portable (ASGI,
  PostgreSQL, `DATABASE_URL`), and so does the frontend (static files).
- `db-f1-micro` is shared-core with no SLA: fine for a lab, not for production.
- One-time work:
  - the `gcp/` module and the `spry-gcp` workspace with WIF;
  - the Cognito / parser origin change via `infra/`;
  - new `gcp-*` make targets;
  - fixing the stale Aurora wording in `infra/backend.yml` / `.env.example`;
  - deleting the three CloudFormation stacks after cutover.

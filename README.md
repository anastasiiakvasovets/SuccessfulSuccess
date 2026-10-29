# SuccessfulSuccess — Meetings

[![Style](https://github.com/dobosevych/SuccessfulSuccess/actions/workflows/style.yml/badge.svg)](https://github.com/dobosevych/SuccessfulSuccess/actions/workflows/style.yml)

A small web app for today's meetings: see what is on today (name, description,
participants) and add a new one from the UI. Built to `SPEC.md`.

- **Frontend** — Next.js (App Router) + shadcn/ui, styled after Canva's visual language
- **Backend** — FastAPI + SQLAlchemy 2 (async) + Alembic
- **Database** — PostgreSQL 17

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

| What | URL |
|------|-----|
| App | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

The backend applies migrations on start.

### Authentication (Cognito)

Every page except `/`, `/login/`, `/auth/callback/` and `/privacy/`, and every `/api/v1` endpoint, needs a
signed-in user, and each user sees only their own meetings. Sign-in is an AWS
Cognito user pool (`infra/auth.tf`, applied by HCP Terraform, see
[Infrastructure](#infrastructure-terraform)): email + password, and Google when
it is configured. Even for local development the pool lives in AWS (it is free
at this scale):

```bash
make aws-auth-env      # prints COGNITO_* lines (from Terraform outputs): paste them into .env
docker compose up -d   # restart so the API and the frontend pick them up
```

**`.env` variables** (never commit `.env`):

| Variable | What it is |
| --- | --- |
| `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_DOMAIN`, `COGNITO_GOOGLE_ENABLED` | Local development only, from `make aws-auth-env`. The AWS build reads them from the Terraform outputs itself |

The pool's own settings (domain prefix, Google client id and secret) are
Terraform variables, not `.env` values: see the variables table below.

**Google client**: in Google Cloud console → *APIs & Services* → *Credentials*,
create an OAuth client of type *Web application* (publish the consent screen, or
add yourself as a test user). Its *Authorized redirect URI* is Cognito's, not the
site's: `https://<domain_prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse`
(`terraform -chdir=infra output -raw google_redirect_uri` prints it).

**Redirect URLs**: Terraform registers `<origin>/auth/callback/` (sign-in) and
`<origin>/` (sign-out) on the app client for the CloudFront domain (read from
the frontend stack) and `local_origin` (`http://localhost:3000`). Cognito
compares them exactly, so `trailingSlash` is on in dev as well. A new
CloudFront distribution therefore needs a Terraform run.

**Deploy order**: the user pool (Terraform) → `aws-deploy-backend` (it needs the
pool to check tokens) → `aws-deploy-frontend` (it bakes the pool's ids and the
parser URL from the Terraform outputs into the build; without them it builds
with sign-in hidden). `make aws-deploy` runs the last two.

**Testing**: open `<site>/login/`. Sign up with an email (Cognito mails a code),
or press *Continue with Google*: Google → Cognito → `<site>/auth/callback/`, which
shows "Signing in…" and then `/today` (or the error, visibly). The header shows
your email and *Sign out*, which also ends the Cognito session. Checks:
`curl -I <site>/login/` (and `/auth/callback/`, `/privacy/`) returns 200;
`<Authority>/.well-known/openid-configuration` (the auth stack's `Authority`
output) loads; `make aws-auth-env` prints the ids.

The first time someone signs in, the frontend sends their ID token to
`POST /api/v1/me/sync`, which stores their profile (email, name, picture,
provider, last login) in the `users` table. Meetings reference `users.id`, the
Cognito `sub`.

Demo data is per user: `make seed owner=<sub>` adds a few meetings for today to
that user (their `sub` is on the user's page in the Cognito console, or `id` in
`GET /api/v1/me`).

> **Ports already in use?** Every host port is configurable in `.env`
> (`FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`). If you change the frontend
> or backend port, update `CORS_ORIGINS` and `NEXT_PUBLIC_API_BASE_URL` to match —
> the browser talks to the published host port, not the compose service name.

## Common tasks

```bash
make up          # start the stack
make down        # stop it
make down-v      # stop it and drop the database volume
make test        # backend test suite (creates meetings_test automatically)
make lint        # ruff + eslint
make migrate     # alembic upgrade head
make seed owner=<sub>  # demo meetings for today for one user
make psql        # psql shell against the app database
make help        # everything else
```

## Windows

The same `make` targets work on Windows, with Docker Desktop (WSL 2 backend)
and [Git for Windows](https://git-scm.com/download/win) installed. There is no
need to install GNU make first: `make.cmd` in the repository root runs the
Makefile, and when `make.exe` is missing it offers to install it with winget
(`ezwinports.make`) and carries on.

```powershell
Copy-Item .env.example .env
.\make help        # PowerShell only runs scripts from the current folder with .\
.\make up-build
```

In `cmd.exe`, plain `make help` finds `make.cmd`; once make is installed,
`make help` works everywhere.

Every recipe runs in Git's bash (`C:/Program Files/Git` by default; pass
`GIT_HOME=...` if it is installed elsewhere), so `make test`, `make seed`, the
`aws-*` targets and the rest behave as on macOS and Linux. Inside WSL, plain
`make` works as on Linux.

Things that are already taken care of, and why:

- `.gitattributes` checks every file out with LF line endings. Git on Windows
  converts to CRLF by default, and a CRLF `entrypoint.sh` stops the backend
  container with `exec /app/entrypoint.sh: no such file or directory`. A clone
  made before `.gitattributes` existed keeps its CRLF files until you run
  `git rm --cached -r . && git reset --hard` (this discards local changes).
- File-change events from a Windows folder do not reach the containers, so hot
  reload polls: `WATCHPACK_POLLING` for Next.js, `WATCHFILES_FORCE_POLLING` for
  uvicorn. For faster reloads keep the clone inside WSL rather than on `C:\`.
- Git's bash rewrites arguments that look like paths (`/aws` becomes
  `C:/Program Files/Git/aws`); the Makefile turns that off with
  `MSYS_NO_PATHCONV`.
- Keep `.env` with LF line endings (copying `.env.example` does): `make` reads
  it directly, and a CRLF `.env` leaves a stray `\r` on every value.

## Infrastructure (Terraform)

Since Lab 7 `infra/` holds two kinds of infrastructure:

| Where | What | How it is changed |
| --- | --- | --- |
| Terraform: `auth.tf`, `reports.tf`, `ai.tf` (+ `versions.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`, `lambda/`) | Cognito sign-in; the weekly report (SES identities, bucket, S3 endpoint, queues, builder and mailer Lambdas, schedule); the agenda parser and its function URL | HCP Terraform, after a push to `main` |
| CloudFormation: `ecr.yml`, `backend.yml`, `frontend.yml` | Image registry; API Lambda + RDS database + network; S3 + CloudFront site | `make aws-ecr`, `make aws-deploy-backend`, `make aws-deploy-frontend` |

The Terraform resources were imported from the former `auth`, `reports` and
`ai` stacks (see [docs/migration/inventory.md](docs/migration/inventory.md) and
`docs/migration/plan-no-changes.txt`). Terraform reads the three CloudFormation
stacks with `data "aws_cloudformation_stack"`, never the other way round.

**State and runs**: organization `ooad-nastyakvasovets`, workspace
`successfulsuccess-dev` in HCP Terraform (`cloud {}` block in `versions.tf`).
**`terraform apply` only happens in HCP Terraform**, after a push to `main`; no
make target and no local command applies. Locally:

```bash
terraform login        # once: stores an HCP Terraform API token
make infra-init        # terraform -chdir=infra init (connects to the workspace)
make infra-fmt         # terraform fmt
make infra-validate    # terraform validate
make infra-plan        # preview what the next run would change (never applies)
```

The `make` targets read Terraform outputs with `terraform -chdir=infra output -raw <name>`
(`user_pool_id`, `issuer`, `queue_url`, `parser_url`, ... — all in `infra/outputs.tf`),
so they need `make infra-init` and `terraform login` once.

**Variables** (`infra/variables.tf`):

| Variable | Default / value | Secret? | Set where |
| --- | --- | --- | --- |
| `project_name`, `aws_region`, `local_origin` | `successfulsuccess`, `us-east-1`, `http://localhost:3000` | no | `infra/terraform.tfvars` |
| `domain_prefix`, `google_client_id` | Cognito domain prefix, Google OAuth client id | no | `infra/terraform.tfvars` |
| `route_table_ids`, `schedule_expression`, `fail_week` | S3 endpoint route tables; `cron(0 7 ? * MON *)`; empty | no | `infra/terraform.tfvars` |
| `architecture`, `parser_provider`, `parser_model`, `anthropic_api_key_parameter`, `log_level` | `x86_64`, `anthropic_api`, `claude-opus-5-5`, `/successfulsuccess/anthropic-api-key`, `INFO` | no (the parameter's *name* only) | `infra/terraform.tfvars` |
| `image_uri` | empty (`<RepositoryUri>:latest`, only for a function created from scratch) | no | default |
| `google_client_secret` | Google OAuth client secret | **yes** (`sensitive`) | HCP workspace variable, **Sensitive** |
| `db_password` | RDS master password, for the builder's `DATABASE_URL` | **yes** (`sensitive`) | HCP workspace variable, **Sensitive** |
| `sender_email`, `report_recipient` | SES sender / recipient addresses | personal, not secret | HCP workspace variables, never in a committed file |

For a run with local execution, the four values in the last rows go into
`infra/secrets.auto.tfvars` (written from `.env`, **gitignored**) or
`$env:TF_VAR_<name>`. The Claude API key itself is not a Terraform variable: it
stays in the SSM SecureString named by `anthropic_api_key_parameter`. Terraform
state holds the secrets in clear text, which is one more reason it lives only in
HCP Terraform.

Changing a setting (the schedule, `fail_week`, the parser model, ...) means
editing `infra/terraform.tfvars` (or the workspace variable), checking it with
`make infra-plan` and pushing to `main`.

**Code is not Terraform's job.** The report builder and the agenda parser run the
backend image, and Terraform ignores their `image_uri` on purpose.
`make aws-update-workers` pushes the image, points both functions at it by
digest (`aws lambda update-function-code`), waits for them
(`aws lambda wait function-updated`) and prints the digest each one runs.
`make aws-deploy-backend` does the same after its migrations, so one backend
deploy ships the API and both workers together. The report mailer's code
(`infra/lambda/report_mailer/`) is ignored too; a change to it goes out by hand.

## Deploy to AWS

`infra/` holds three CloudFormation templates deployed by `make`: `ecr.yml`
(image registry), `backend.yml` (API and database) and `frontend.yml` (site);
sign-in, the weekly report and the agenda parser are Terraform (see above).
`make` reads `.env`,
so the `aws-*` targets pick up the credentials and settings from there; `.env` is
gitignored, so real keys never reach the repository. The AWS CLI runs in the
`amazon/aws-cli` container, so nothing has to be installed on the host besides
Docker (`AWS=aws make aws-deploy` uses a local CLI instead, which is noticeably
faster).

```
browser ──https──→ CloudFront (optional custom domain) → private S3 bucket (Next.js static export)
   └────https──→ Lambda function URL → Lambda → Aurora Serverless v2 :5432
```

Every resource lives in `AWS_REGION`, **us-east-1** by default, which is also
where CloudFront reads its certificates from. There is no API Gateway or load
balancer: the browser calls the API on its function URL, and FastAPI's CORS
settings allow it.

Every stack is tagged `PROJECT_NAME=<value of PROJECT_NAME>`, and every resource
that accepts tags also carries it explicitly in the templates. Filter by it in
Cost Explorer or Resource Groups to see everything the project owns.

### One command

```bash
make aws-whoami   # check the credentials work
make aws-deploy   # the backend, then the frontend built against it
```

`aws-deploy` runs the two steps below in order: the backend checks tokens from
the user pool, and the frontend bakes the API URL and the pool's ids into its
build. Each step can also run on its own. The user pool, the report and the
parser come from HCP Terraform, not from these targets.

The backend Lambda sits in a VPC with no internet access, so it cannot download
the pool's signing keys itself; `aws-deploy-backend` fetches them
(`<issuer>/.well-known/jwks.json`, `issuer` from the Terraform outputs) and
passes them in as `COGNITO_JWKS`.

Fill these in `.env` first:

```bash
AWS_ACCESS_KEY_ID=...        # an IAM user, not root access keys
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
PROJECT_NAME=successfulsuccess   # prefixes every resource name, and the PROJECT_NAME tag
AWS_DB_PASSWORD=...          # 8-41 chars, [A-Za-z0-9_-] only
AWS_CORS_ORIGINS=            # empty: follow the frontend's URLs (* until it exists)
AWS_FRONTEND_DOMAIN=         # optional, e.g. app.example.com
```

### 1. Backend — Lambda function URL, Aurora Serverless v2

```bash
make aws-deploy-backend   # ECR + build & push + create/update the stack + migrate + update the workers, prints the URL
```

The API runs as a **Lambda function** from a container image
(`backend/Dockerfile.lambda`): the same FastAPI app, adapted to Lambda by
[Mangum](https://github.com/Kludex/mangum) in `app/lambda_handler.py`. Requests
reach it through its **function URL** (`https://<id>.lambda-url.<region>.on.aws`),
Lambda's own public HTTPS endpoint, and that URL is the backend URL the frontend
is built with. FastAPI keeps doing the routing, CORS and error envelope exactly
as it does locally. `backend/Dockerfile` stays the local/compose image.

The database is an **Aurora Serverless v2** PostgreSQL cluster with one
`db.serverless` writer at the smallest size Aurora allows: it scales between
0 and 1 ACU (`DbMinCapacity`, `DbMaxCapacity`) and **pauses after 5 idle
minutes** (also the minimum), so an unused deployment
pays only for storage. The first connection after a pause waits ~15 s while it
resumes; the function's 60 s timeout covers that.

The function sits in the account's **default VPC**, next to the cluster, so the
database is never public: its security group only accepts the function's. The
function needs nothing else on the network, so there is no NAT gateway.

Migrations run in the same function: invoked directly with
`{"action": "migrate"}` it applies them instead of serving a request. Function
URL events never carry that key, so no web request can trigger it.
`make aws-deploy-backend` invokes it after every deploy, so migrations run once
per deploy rather than racing on each cold start.

The first deploy takes ~15 minutes; Aurora is the slow part. It is idempotent —
run it again to ship a new version. The image is passed to the stack by digest,
not by tag, so every push really does update the function. If the stack is
still busy with an earlier update, the target waits for it rather than failing.

| Command | What it does |
|---------|--------------|
| `make aws-url` | Print the API URL (`/docs` for Swagger, `/health` for the check) |
| `make aws-status` | Stack outputs plus the API function's state |
| `make aws-logs` | Follow the function logs from CloudWatch |
| `make aws-migrate` | Apply migrations again on their own |
| `make aws-update-workers` | Push the image and put it on the report builder and agenda parser (prints their digests) |
| `make aws-destroy` | Delete the CloudFormation stacks (asks first — the database goes too); refuses while Terraform still manages sign-in, reports and the parser |

The image is built for `AWS_LAMBDA_ARCH` (`x86_64` by default).
`AWS_LAMBDA_ARCH=arm64 make aws-deploy-backend` is ~20% cheaper and builds
natively on Apple Silicon. The image platform follows this variable, so the two
cannot drift apart. The build passes `--provenance=false` because Lambda rejects
the multi-manifest image index that BuildKit otherwise pushes.

### 2. Frontend — S3 + CloudFront

```bash
make aws-deploy-frontend   # create/update the stack, build against the API URL, upload
make aws-frontend-url      # print the site URL
```

The target refuses to run until the backend stack exists. It reads the
backend's function URL from that stack, builds the Next.js **static export** in
Docker with `NEXT_PUBLIC_API_BASE_URL` set to it, syncs the files to a
**private S3 bucket** and invalidates the **CloudFront** distribution in front
of it. The site is served over HTTPS at `https://<id>.cloudfront.net`. A new
distribution takes ~5 minutes to come up.

- The distribution is on CloudFront's **flat-rate Free plan**
  (`AWS::PricingPlanManager::Subscription`): $0 a month for 1M requests and
  100 GB, with no overage charges, WAF and DDoS protection included. The plan
  requires a web ACL of its own, so the stack creates one that allows
  everything. AWS allows 3 Free plans per account and refuses them while the
  account is on the AWS Free Tier; set `AWS_CLOUDFRONT_PLAN=PAY_AS_YOU_GO` there.
  `PricingPlanStatus` in the stack outputs reads `ACTIVE` once it applies.
- The bucket blocks all public access. CloudFront reads it through **origin
  access control**, and the bucket policy admits only this distribution.
- The export is built with `trailingSlash`, so each route is a folder with an
  `index.html` (`/meetings/new/`). A small CloudFront Function maps clean URLs
  onto those files, since S3's REST endpoint has no index documents. Anything
  missing gets the export's `404.html` with a 404 status.
  `output` stays `standalone` for the compose/production image and switches to
  `export` only when `NEXT_OUTPUT=export` is set, which is the deploy target's
  job.
- HTML is uploaded with `no-cache` and the hashed assets with a one-year
  immutable header, and every deploy invalidates `/*`, so a new version shows up
  on the next page load.
- With `AWS_CORS_ORIGINS` empty, the backend allows exactly the frontend's
  origins (the CloudFront URL and the custom domain). On the very first
  `make aws-deploy` the frontend does not exist yet, so the API starts with `*`;
  the frontend step says so, and the next `make aws-deploy-backend` locks it down.

### 3. Custom domain for the frontend (optional)

```bash
# .env
AWS_FRONTEND_DOMAIN=app.example.com

make aws-frontend-cert      # request + DNS-validate the certificate in us-east-1
make aws-deploy-frontend    # attach the domain to the distribution
make aws-deploy-backend     # add the new origin to the API's CORS
```

CloudFront only reads ACM certificates from **us-east-1**, and that is where
everything is deployed. `make aws-frontend-cert` (`infra/certificate.sh`) reuses
an issued or pending certificate for the domain, or requests one, then waits for
DNS validation. If the domain's Route 53 hosted zone is in this account, it
writes the validation record itself, and the frontend stack adds the A/AAAA
alias records pointing at the distribution. Otherwise both print the records
to add at your DNS provider: the validation CNAME, then a CNAME from the domain
to the distribution's `*.cloudfront.net` name.

The API keeps its function URL: a function URL cannot take a custom domain.

### 4. Weekly report (Lab 5)

Every Monday at 07:00 Kyiv time a CSV of last week's meetings is built, saved to S3 and emailed.
Everything is in `infra/reports.tf` (Terraform, applied by HCP Terraform):

- **EventBridge Scheduler** (`cron(0 7 ? * MON *)`, Europe/Kyiv) and `make report-now` put
  `{"week": ..., "source": ...}` on the SQS queue `report-requests` (3 attempts, then `report-requests-dlq`).
- The **report builder** Lambda (the backend image, handler `app.reports.lambda_handler.handler`, in the
  VPC next to the database) reads the meetings and writes `reports/<week>.csv`. With no NAT, it reaches
  S3 through a free gateway endpoint.
- That upload's `ObjectCreated` event starts the **report mailer** Lambda (`infra/lambda/`, outside
  the VPC), which sends the CSV as an attachment through **SES**. The builder does not know it exists.
- Reports expire after 90 days. In the SES sandbox the sender (`sender_email`) and recipient
  (`report_recipient`, both Terraform variables) must be verified addresses: SES mails each a link
  when its identity is created.

```bash
make seed-weeks                    # local: demo meetings over the last two ISO weeks
make report-local WEEK=2026-W41    # local: print one week's CSV from the compose database
make report-now WEEK=2026-W40      # build (and email) one week's report on demand, through SQS
make dlq-status                    # messages waiting / in flight in the queue and the DLQ
```

`schedule_expression = "rate(5 minutes)"` fires the schedule every 5 minutes for testing; set it
back to `cron(0 7 ? * MON *)` afterwards (both through a Terraform run).

**Testing the dead-letter queue:** `fail_week = "2026-W01"` makes the builder raise for that week.
`make report-now WEEK=2026-W01`, then watch `make dlq-status`: each failed attempt comes back after the
6-minute visibility timeout, and after the third (~12 minutes) the message is in the DLQ. Clear
`fail_week` again, then move the message back with **Start DLQ redrive** in the SQS console (or
`aws sqs start-message-move-task --source-arn <dlq arn>`); this time the report is built and mailed.

### Cost

- **Lambda** — 1M requests and 400,000 GB-seconds a month, always free. The
  function URL costs nothing beyond the invocation.
- **Aurora Serverless v2** is not in the free tier. It bills per ACU-hour while
  awake, nothing for compute while paused, plus storage and I/O. A demo that
  sits idle costs cents a month.
- **CloudFront** — the flat-rate Free plan: $0, 1M requests and 100 GB a month,
  never an overage charge (traffic past it may be slowed, not billed).
  **S3** — 5 GB and 20,000 GETs in the free tier; CloudFront caches most reads.
  ACM certificates are free.
- **ECR** — 500 MB in the free tier; the lifecycle policy keeps five images.

`make aws-destroy` deletes the CloudFormation stacks, database included, with no
snapshot left behind; the Terraform resources go first, with a destroy run in
HCP Terraform. Accounts opened after July 2025 get credits instead of the classic free
tier — check your billing console rather than assuming.

### Known trade-offs

- **No custom domain on the API**: function URLs cannot take one. Putting one on
  it would need API Gateway or a second CloudFront distribution in front.
- The database password reaches the function as a plain environment variable.
  Moving it to SSM Parameter Store or Secrets Manager is the first thing to
  harden.
- **Cold starts**: the first request after a few idle minutes waits ~1–2 s while
  Lambda starts the container, and up to ~15 s more if Aurora has paused.
- Every warm instance holds one database connection. Nothing is reserved by
  default (`MaxConcurrency=0`): new accounts have a Lambda concurrency limit of
  10 in total and Lambda refuses to reserve any of it, so that limit is the cap,
  well under the cluster's connection limit. Once the limit is raised, set
  `MaxConcurrency` to keep a spike off the database; requests beyond it get
  HTTP 429. RDS Proxy is the proper fix, and it is not free.
- The function URL is public: FastAPI checks the Cognito access token on every
  `/api/v1` request, but there is no request throttling in front of it beyond
  the concurrency limit.
- Cognito sends its emails (sign-up codes, password resets) itself, capped at 50
  a day. Switch the pool to SES before real traffic.
- Signing up with a password and later with Google under the same email makes
  two separate Cognito users, with separate meetings. Linking them needs a
  pre-sign-up Lambda trigger.
- Deleting the backend stack takes ~20 minutes: Lambda releases its VPC network
  interfaces slowly, and the security groups wait for them.
- One Aurora instance: there is no reader to fail over to.

## API

Base path `/api/v1`. Full schema at `/docs`. Everything under it needs
`Authorization: Bearer <Cognito access token>` (`401` otherwise) and only ever
touches the caller's own meetings: someone else's meeting is a `404`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/meetings?date=&q=&limit=&offset=` | Meetings overlapping a day (today by default) |
| `GET` | `/meetings/{id}` | One meeting |
| `POST` | `/meetings` | Create a meeting |
| `PUT` | `/meetings/{id}` | Replace a meeting's details and participants |
| `DELETE` | `/meetings/{id}` | Delete a meeting and its participants |
| `GET` | `/me` | The signed-in user's profile |
| `POST` | `/me/sync` | Store the profile from the user's ID token (after sign-in) |
| `GET` | `/health` | Liveness + database check |

Every error uses one envelope:

```json
{ "error": { "code": "validation_error", "message": "…", "details": [{ "field": "ends_at", "message": "…" }] } }
```

### Time handling

Timestamps are stored in UTC and **served with the application timezone's offset**
(`APP_TIMEZONE`, default `Europe/Kyiv`). "Today" is that timezone's calendar day,
and a meeting is listed if it *overlaps* the day — so a 23:00–00:30 meeting appears
on both days. The UI reads the wall-clock time straight from the offset the API
sent, so every client shows the same time as the day it was listed under.

## Layout

```
backend/    FastAPI app (api → services → repositories → models), Alembic, tests
frontend/   Next.js app, shadcn/ui primitives in components/ui
infra/      Terraform (auth, reports, ai; HCP Terraform) and the CloudFormation templates behind the aws-* targets
docker-compose.yml
```

## Continuous integration

`.github/workflows/style.yml` runs on every push to `main` and gates style only:

| Job | Runs | Against |
|-----|------|---------|
| Backend — ruff | `ruff check` (GitHub annotations) + `ruff format --diff` | `backend/` |
| Frontend — ESLint | `npm ci` + `npm run lint` | `frontend/` |

Ruff is pinned to the version the backend image ships (0.16.6) and Node matches
the container's Node 22, so CI and local containers agree on what passes.

Reproduce either job locally:

```bash
make lint                                   # both, through the running containers
cd backend  && uvx ruff@0.16.6 check . && uvx ruff@0.16.6 format --diff .
cd frontend && npm ci && npm run lint
```

There is no deploy (CD) stage — no target is configured yet.

## Development notes

- The backend bind-mounts `./backend`, so `uvicorn --reload` picks up edits live.
- The frontend runs `next dev` in the container with the same bind mount.
- Backend tests run against a real Postgres (`meetings_test`), truncating tables
  between tests; `make test` creates that database if it is missing.

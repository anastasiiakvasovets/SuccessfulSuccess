# CLAUDE.md

Meetings app: FastAPI backend (`backend/`), Next.js frontend (`frontend/`), CloudFormation
templates (`infra/`), one `Makefile` that drives both local development and AWS deploys.
`README.md` and `SPEC.md` describe the app; this file holds working notes for the labs.

## Lab 5 — weekly report built by events

The assignment is in [docs/lab5.md](docs/lab5.md). Read it before working on the lab.

### Ground rules (from the owner)

- `PROJECT_NAME=successfulsuccess`. Region for everything: **us-east-1** (the AWS CLI's default
  region is us-east-1 too). Account `980553487282`, IAM user `lab-user`.
- Lab 4 stacks, all in us-east-1: `successfulsuccess-backend`, `successfulsuccess-frontend`,
  `successfulsuccess-auth`, `successfulsuccess-ecr`. Old stacks with the same ecr/auth names exist
  in **eu-central-1**: ignore them, never deploy there.
- No custom domain: the frontend is on the default CloudFront URL
  (`https://d2yc332l6c63ao.cloudfront.net`). SES sends from a **verified email address**, not
  `reports@<domain>`; there is no DKIM/DNS step.
- The owner works in Windows PowerShell. Every command and Makefile target must work there.
- Work directly on `main` (it's a fork). No branches. Commit only when asked.
- All new Lab 5 infra goes into **one** template, `infra/reports.yml`, deployed as stack
  `successfulsuccess-reports` and tagged `PROJECT_NAME=successfulsuccess` like the others.
- No secrets or email addresses hardcoded in code or templates: pass them as parameters from `.env`.
- The database is **RDS PostgreSQL `db.t3.micro`, not Aurora** (changed in commit `c0307bd`). Where
  the lab text says "Aurora", read "the RDS instance". It does not pause, so it has no resume delay
  and bills per hour whether or not anything queries it.

### Tooling on this machine

- GNU make is installed (winget `ezwinports.make`, on PATH as `make.exe`). From PowerShell, `make
  <target>` works; `.\make <target>` (`make.cmd`) is the fallback that installs make if missing.
  The Makefile switches its shell to Git for Windows' `bash.exe` (`C:/Program Files/Git`), so
  recipes are POSIX shell: write new targets in the same style as the existing ones.
- `.env` is gitignored and is `-include`d by the Makefile; its assignments beat shell exports.
  Override on the command line instead (`make report-now WEEK=2026-W39`).
- The Makefile runs the AWS CLI in a container (`amazon/aws-cli:latest`) with the credentials from
  `.env`. `AWS=aws make <target>` uses the host CLI (v2) instead.
- Avast antivirus is installed. Its HTTPS scanning is excluded for `amazonaws.com`, so the host
  `aws` CLI and `make aws-whoami` both work without `AWS_CA_BUNDLE` (checked 2026-10-13). If
  `CERTIFICATE_VERIFY_FAILED` comes back, that exclusion has been lost.

### How templates are deployed and tagged

Every stack is deployed with `aws cloudformation deploy`, from a make target, the same way:

```
$(call wait-stack-idle,<stack>)       # wait out *_IN_PROGRESS
$(call clear-failed-create,<stack>)   # delete a ROLLBACK_COMPLETE / REVIEW_IN_PROGRESS stack
$(AWS) cloudformation deploy \
    --stack-name <stack> --template-file infra/<file>.yml \
    --capabilities CAPABILITY_IAM \   # only for templates that create IAM roles
    --no-fail-on-empty-changeset \
    $(STACK_TAGS) \                   # --tags "PROJECT_NAME=$(PROJECT_NAME)"
    --parameter-overrides "ProjectName=$(PROJECT_NAME)" ...
```

Stack names come from `$(PROJECT_NAME)-<suffix>` variables (`APP_STACK`, `ECR_STACK`, ...);
outputs are read with `$(call stack-output,<stack>,<OutputKey>)`. Templates also put a
`PROJECT_NAME` tag on resources explicitly. Every template has a `ProjectName` parameter
defaulting to `successfulsuccess`.

| Target | Stack / template |
| --- | --- |
| `make aws-ecr` | `successfulsuccess-ecr` / `infra/ecr.yml` |
| `make aws-push` | builds and pushes the backend image (runs `aws-ecr` first) |
| `make aws-deploy-backend` | `successfulsuccess-backend` / `infra/backend.yml` (runs `aws-push` first, then `aws-migrate`) |
| `make aws-deploy-auth` | `successfulsuccess-auth` / `infra/auth.yml` |
| `make aws-deploy-frontend` | `successfulsuccess-frontend` / `infra/frontend.yml` |
| `make aws-logs` / `aws-status` / `aws-migrate` | backend function helpers |

### Backend Lambda: network (looked up with the AWS CLI on 2026-10-13)

- Function `successfulsuccess-backend`, image package, x86_64, 512 MB, timeout 60 s, log group
  `/aws/lambda/successfulsuccess-backend` (Text format, 7-day retention).
- VPC `vpc-004bed0269ebdd3c1`: the account's **default VPC**, 172.31.0.0/16. The Makefile finds it
  with `ec2 describe-vpcs --filters Name=isDefault,Values=true` and passes it as `VpcId`.
- Subnets (all six default subnets, passed as `SubnetIds`):
  `subnet-0de4f6e4ba3c84ca4` (1a), `subnet-016d3d8922d07b9ba` (1b), `subnet-00134febdfd85228c` (1c),
  `subnet-0a740e8b41f9387bb` (1d), `subnet-039f19b3d13168e45` (1e), `subnet-01ef75e3d017b35ed` (1f).
- Route tables: one, `rtb-0fda711f924ebbb89`, the VPC's **main** route table. No subnet has an
  explicit association, so all six use it. Routes: `172.31.0.0/16 → local`,
  `0.0.0.0/0 → igw-06a8f4f804954e7b8`. The internet route does not help the Lambda: VPC Lambda ENIs
  get no public IP, and there is **no NAT gateway**.
- VPC endpoints: **none**. There is no S3 gateway endpoint yet; `infra/reports.yml` must create it
  (`com.amazonaws.us-east-1.s3`, `RouteTableIds: [rtb-0fda711f924ebbb89]`). Look the route table up
  at deploy time rather than hardcoding it, like the Makefile does for the VPC and subnets.
- Security group of the function: `sg-06b7e429066e1c5f3` (`FunctionSecurityGroup`, no inbound,
  all outbound). The database's SG `sg-050a697dbe192fd34` allows 5432 only from that group, so the
  report builder must use `sg-06b7e429066e1c5f3` (or the DB SG must get a new ingress rule).
  The backend stack does not export these ids; read them from its resources or the function config.
- Function role `successfulsuccess-backend-FunctionRole-01NooiWHoXCK`: only
  `AWSLambdaVPCAccessExecutionRole`. The builder needs its own role (VPC access + `s3:PutObject` on
  `reports/*` + SQS receive/delete).

### Backend image

- Built from `backend/Dockerfile.lambda` (base `public.ecr.aws/lambda/python:3.12`, deps installed
  with `uv pip install -r pyproject.toml`, copies `alembic.ini`, `alembic/`, `app/`).
  Default `CMD ["app.lambda_handler.handler"]`. A second handler is selected with
  `ImageConfig: { Command: ["app.reports.lambda_handler.handler"] }`.
- `boto3` is not in `pyproject.toml`; the Lambda Python base image ships it. Locally (compose image)
  it is absent.
- Repository `980553487282.dkr.ecr.us-east-1.amazonaws.com/successfulsuccess-backend`
  (`successfulsuccess-ecr` output `RepositoryUri`). Lifecycle keeps the 5 newest images.
- `make aws-push`: `ecr get-login-password | docker login`, then
  `docker build --platform linux/amd64 --provenance=false -f backend/Dockerfile.lambda
  -t <repo>:$(IMAGE_TAG) ./backend` and `docker push` (`IMAGE_TAG` defaults to `latest`).
- The stack is deployed with the image **pinned by digest**: `make aws-deploy-backend` resolves
  the `latest` tag to a digest and passes `ImageUri=<repo>@sha256:...`. Currently deployed:
  `...successfulsuccess-backend@sha256:d8b853a8a671c9c280b29892d9d37ecbef0d724bb4bd0a5ff7a9966005ab1989`
  (pushed 2026-09-30). The reports stack should resolve the digest the same way.

### Database connection (API Lambda)

- The database is **RDS PostgreSQL 16, `db.t3.micro`**, instance `successfulsuccess-db`, endpoint
  `successfulsuccess-db.cq5sm6qqgpxq.us-east-1.rds.amazonaws.com:5432`, database `meetings`, user
  `app` (backend stack output `DatabaseEndpoint`). It is **not Aurora**, despite the lab text and
  parts of `README.md`; it does not pause, so there is no ~15 s resume, but keep the builder
  timeout at 60 s anyway.
- Env vars on the function: `DATABASE_URL`
  (`postgresql+asyncpg://app:<AWS_DB_PASSWORD>@<endpoint>:5432/meetings`, password in plain text in
  the function config), `APP_TIMEZONE=Europe/Kyiv`, `LOG_LEVEL`, `CORS_ORIGINS`, `COGNITO_REGION`,
  `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_JWKS`. No Secrets Manager / SSM.
  The builder only needs `DATABASE_URL`, `APP_TIMEZONE`, `LOG_LEVEL`; build `DATABASE_URL` from the
  `DbPassword` parameter (`AWS_DB_PASSWORD` in `.env`) and the backend stack's `DatabaseEndpoint`.
- `app/config.py` (`Settings`, pydantic-settings) reads them; `app/db.py` creates one module-level
  async engine (`create_async_engine`, asyncpg) and `SessionFactory`. Code is async throughout.

### Meetings data model (`backend/app/models/`, migrations `0001`, `0002`)

- `meetings`: `id` UUID pk; `owner_id` varchar(128) → `users.id` (nullable, cascade delete);
  `name` varchar(200) (**the title**); `description` text; `location` varchar(200);
  `starts_at`, `ends_at` timestamptz (check `ends_at > starts_at`; **duration = ends_at − starts_at**,
  not stored); `created_at`, `updated_at`. Indexes on `starts_at` and `(owner_id, starts_at)`.
- `participants`: `id` UUID pk; `meeting_id` → `meetings.id` (cascade); `name` varchar(120);
  `email` varchar(255) nullable; `position` int. Free text, **not linked to `users`**.
  Participant count = rows per meeting.
- `users`: `id` = Cognito `sub` (pk); `email`, `email_verified`, `name`, `given_name`,
  `family_name`, `picture_url`, `auth_provider` ("cognito"/"google"), timestamps, `last_login_at`.
- The organiser is the meeting's owner (`owner_id` → `users`). There is no members/attendees
  relation to users beyond the free-text participants. Per-person breakdown = per owner.
- Times are stored in UTC; the app's day windows use `APP_TIMEZONE` (Europe/Kyiv). ISO weeks for the
  report should be computed in that timezone too (see `day_window` in `app/services/meeting.py`).

### Running locally (docker compose)

- `make up` / `make up-build` (`docker compose up [--build]`), `make down`, `make down-v` (drops the
  `pgdata` volume), `make logs`, `make ps`.
- Services: `db` (postgres:17-alpine, user/password/db `app`/`app`/`meetings`, host port 5432),
  `backend` (built from `backend/Dockerfile` with dev deps, `uvicorn --reload` on :8000, `./backend`
  bind-mounted to `/app`, runs `alembic upgrade head` on start), `frontend` (:3000).
- Inside compose the backend uses `postgresql+asyncpg://app:app@db:5432/meetings`; from the host
  use `localhost:5432`.
- `make migrate`, `make psql`, `make shell-backend`, `make seed owner=<cognito-sub>` (demo meetings
  for today), `make test` (creates `meetings_test`, runs pytest in the backend container),
  `make lint` (ruff + eslint), `make fmt`.
- Run report code against the compose DB with e.g.
  `docker compose exec backend python -m app.reports.weekly 2026-W40` (once such a module exists).

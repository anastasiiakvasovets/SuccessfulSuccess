# CLAUDE.md

Meetings app: FastAPI backend (`backend/`), Next.js frontend (`frontend/`), infrastructure in
`infra/` (Terraform for auth, reports, ai since Lab 7; CloudFormation for ecr, backend,
frontend), one `Makefile` that drives both local development and AWS deploys.
`README.md` and `SPEC.md` describe the app; this file holds working notes for the labs.

## Lab 7 — auth, reports and ai moved to Terraform

- `infra/auth.tf`, `reports.tf`, `ai.tf` (+ `versions.tf`, `variables.tf`, `outputs.tf`,
  `terraform.tfvars`, `lambda/report_mailer/`) replace `auth.yml`, `reports.yml`, `ai.yml`, which are
  deleted. The resources were imported from the old stacks (deleted with `Retain`); the record is
  `docs/migration/` (`inventory.md`, `plan-no-changes.txt`, `<stack>-resources.txt`).
- State: HCP Terraform, organization `ooad-nastyakvasovets`, workspace `successfulsuccess-dev`.
  **Never run `terraform apply`**, and no make target does: apply happens only in HCP Terraform after
  a push to `main`. Locally: `make infra-init` / `infra-fmt` / `infra-validate` / `infra-plan`.
- Secrets (`google_client_secret`, `db_password`) and the emails (`sender_email`,
  `report_recipient`) are never in a committed file: HCP workspace variables (Sensitive for the
  secrets), or `infra/secrets.auto.tfvars` (gitignored, and excluded by `infra/.terraformignore`)
  for local execution. Non-secret values are in `infra/terraform.tfvars`.
- The Makefile reads outputs with `$(call tf-output,<name>)` = `terraform -chdir=infra output -raw
  <name>` (names in `infra/outputs.tf`: `user_pool_id`, `issuer`, `queue_url`, `dlq_url`,
  `parser_url`, ...). Settings such as the schedule, `fail_week` or the parser model are Terraform
  variables now, changed through `terraform.tfvars` and a push.
- Terraform ignores `image_uri` of the report builder and the agenda parser: `make
  aws-update-workers` (also run by `make aws-deploy-backend`, after `aws-migrate`) pins both on the
  pushed image by digest. The mailer's zip is ignored too; a change to it goes out by hand.
- The three CloudFormation stacks stay and are read by Terraform with `data
  "aws_cloudformation_stack"`. A new CloudFront domain needs a Terraform run (Cognito callbacks and
  parser CORS come from it).
- Below, Lab 5 and Lab 6 notes describe the CloudFormation era where they mention `reports.yml`,
  `ai.yml` or their deploy targets.

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
- All Lab 5 infra is in `infra/reports.tf` (was the template `infra/reports.yml`, stack
  `successfulsuccess-reports`), tagged `PROJECT_NAME=successfulsuccess` like the others.
- No secrets or email addresses hardcoded in code, templates or `.tf`/`.tfvars` files: pass them
  as parameters / Terraform variables (see Lab 7).
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
- Avast antivirus is installed. Its HTTPS scanning is excluded for `*.amazonaws.com` and
  `*.api.aws` (Bedrock's Messages API endpoint, `bedrock-mantle.us-east-1.api.aws`), so the host
  `aws` CLI and `make aws-whoami` both work without `AWS_CA_BUNDLE`. The exclusion was lost once
  and restored on 2026-10-27: if `CERTIFICATE_VERIFY_FAILED` comes back, it has been lost again.
  The containerised CLI and the compose backend are unaffected either way.
- Docker Desktop must be running for every `make aws-*` target (the CLI runs in a container).
- In Claude Code's Bash tool, a heredoc mangles `\` + newline (Makefile and Dockerfile line
  continuations come out as a literal `\n`). Edit such files with the Edit/Write tools instead.

### How templates are deployed and tagged

The three remaining stacks (ecr, backend, frontend) are deployed with `aws cloudformation
deploy`, from a make target, the same way:

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
| `make aws-deploy-backend` | `successfulsuccess-backend` / `infra/backend.yml` (runs `aws-push` first, then `aws-migrate`, then updates the worker functions) |
| `make aws-update-workers` | `update-function-code` on the report builder and agenda parser (runs `aws-push` first) |
| `make aws-deploy-frontend` | `successfulsuccess-frontend` / `infra/frontend.yml` |
| `make aws-logs` / `aws-status` / `aws-migrate` | backend function helpers |
| `make aws-auth-env` / `report-now` / `dlq-status` | read Terraform outputs (auth, reports) |
| `make aws-ai-url` / `aws-logs-ai` / `aws-agendas` | agenda parser helpers (Lab 6) |
| `make infra-init` / `infra-fmt` / `infra-validate` / `infra-plan` | Terraform in `infra/`; never apply |

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
- VPC endpoints: before Lab 5, none. `infra/reports.tf` has the S3 gateway endpoint
  (`com.amazonaws.us-east-1.s3`) on `var.route_table_ids` (`rtb-0fda711f924ebbb89`).
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
  Default `CMD ["app.lambda_handler.handler"]`. Other handlers are selected with
  `ImageConfig: { Command: [...] }`: `app.reports.lambda_handler.handler` (report builder, Lab 5)
  and `app.ai.agenda_lambda.handler` (agenda parser, Lab 6).
- `boto3` is only in the `dev` dependency group (tests, compose image): the Lambda Python base image
  ships it, and `Dockerfile.lambda` installs only `[project].dependencies`.
- Repository `980553487282.dkr.ecr.us-east-1.amazonaws.com/successfulsuccess-backend`
  (`successfulsuccess-ecr` output `RepositoryUri`). Lifecycle keeps the 15 newest images; every
  function is pinned to a digest, so check that the pinned ones survive before pushing a lot.
- `make aws-push`: `ecr get-login-password | docker login`, then
  `docker build --platform linux/amd64 --provenance=false -f backend/Dockerfile.lambda
  -t <repo>:$(IMAGE_TAG) ./backend` and `docker push` (`IMAGE_TAG` defaults to `latest`).
- The stack is deployed with the image **pinned by digest**: `make aws-deploy-backend` resolves
  the `latest` tag to a digest and passes `ImageUri=<repo>@sha256:...`; `make aws-update-workers`
  pins the report builder and agenda parser on the same digest (Terraform ignores their image).
  Deployed on 2026-10-27: the API and the agenda parser on
  `...successfulsuccess-backend@sha256:e57dac2c7a7c67c65927cb6b4e0064ddef6441a3640b7bfa0209a05f8aa331af`;
  the report builder still on `sha256:b3b0804f...` (2026-10-14) until `make aws-update-workers`.

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

### Meetings data model (`backend/app/models/`, migrations `0001`–`0003`)

- `meetings`: `id` UUID pk; `owner_id` varchar(128) → `users.id` (nullable, cascade delete);
  `name` varchar(200) (**the title**); `description` text; `location` varchar(200);
  `starts_at`, `ends_at` timestamptz (check `ends_at > starts_at`; **duration = ends_at − starts_at**,
  not stored); `created_at`, `updated_at`. Indexes on `starts_at` and `(owner_id, starts_at)`.
  Since `0003` (Lab 6): `agenda` JSONB (`{"items": [...], "action_items": [...]}`), and
  `ai_suggestion` JSONB, `ai_model` varchar(100), `ai_prompt_version` varchar(50) (see Lab 6 below).
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
- Lab 6, in the backend container with the `.env` AWS credentials: `make llm-hello`,
  `make parse TEXT="..."` (or `FILE=agenda.txt`), `make agendas-local`.

## Lab 6 — Paste an agenda (LLM parser)

The assignment is in [docs/labs/lab6.md](docs/labs/lab6.md); only Part 4 is built. The decision
record is [docs/adr/0006-llm-agenda-parsing.md](docs/adr/0006-llm-agenda-parsing.md), the diagram
[docs/architecture/c4-container.md](docs/architecture/c4-container.md).

### Ground rules (from the owner)

- Lab 6 infra lives in `infra/ai.tf` (was the template `infra/ai.yml`, stack
  `successfulsuccess-ai`), tagged `PROJECT_NAME` like the others.
- The model is a **setting**, never code: `PARSER_PROVIDER` (`anthropic` = Messages API on Bedrock
  via `AnthropicBedrockMantle`; `converse` = Bedrock Converse; `anthropic_api` = the Claude API
  via `anthropic.Anthropic()`, same request as `anthropic`; `fake` = no model) and
  `PARSER_MODEL`. Make variables, defaults `anthropic` / `anthropic.claude-opus-5-5`; `.env` sets
  `PARSER_PROVIDER=fake`, so pass the provider on the command line for real calls. The two candidates: Claude Opus 5.5 (`anthropic.claude-opus-5-5`,
  the lab's target) or Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, Converse).
- Bedrock is **blocked account-wide** (checked 2026-10-28, Paid plan). AWS Support declined the
  quota increase on 2026-10-28 (case 179312089700299) until there is usage history and a full
  billing cycle, so the Claude API fallback stays for now:
  every model tried is refused before inference, either "not available for this account"
  (Claude Opus 5.5 / Haiku 5.5, GPT-6 / 6.1) or a daily token quota of 0 (Claude 4.x, Nova,
  Llama, Mistral, gpt-oss). Don't try more Bedrock models; it is not a code problem.
- **Deployed now: the Claude API as a fallback**, `PARSER_PROVIDER=anthropic_api`,
  `PARSER_MODEL=claude-opus-5-5`. The key: `ANTHROPIC_API_KEY` in `.env` locally (passed into
  the container by name only); in Lambda the SSM SecureString `/successfulsuccess/anthropic-api-key`
  (`aws/ssm` key), read once at cold start by `providers.warm_up()`; the role has
  `ssm:GetParameter` on exactly that parameter. Never print, log or echo the key, and never put
  it in a template, an env var of the function, or a command line. Back to Bedrock later:
  `parser_provider = "anthropic"`, `parser_model = "anthropic.claude-opus-5-5"` in
  `infra/terraform.tfvars`, then a push (HCP Terraform applies).
- Each `make llm-hello` / `make parse` against a real model costs real money (≈ $0.012 per Opus
  5.5 parse): ask before running loops of them.
- IAM stays `bedrock-mantle:CreateInference` + `bedrock:InvokeModel` on `"*"` (narrowing it is a
  discussion answer, not a change). Prices in `app/ai/pricing.py`: the lab's table, plus Haiku 4.5
  at $1 / $5 per 1M tokens, the Claude API ids `claude-opus-5-5` / `claude-haiku-5-5`, and
  `fake` at $0. A model id missing there logs `cost_usd: null`: add it when you add a model.
- The AWS budget `monthly-5usd` already exists (made by hand): do not create another. Budget JSON
  files hold the owner's email and are gitignored.
- Still to do once a model answers: the five-input test table, one `agenda_parsed` log line, the
  written answers, the screen recording, and the two `TODO` placeholders in ADR 0006.

### How it fits together

- `backend/app/ai/`: `agenda.py` (schemas `ParsedAgenda`/`AgendaItem`/`ActionItem`, `SYSTEM`,
  `PROMPT_VERSION = "agenda-v1"`, `parse_agenda`, one retry on a validation error),
  `providers.py` (one interface, three providers; throttling → `ModelBusyError`), `pricing.py`,
  `agenda_lambda.py` (the handler), `hello.py` (`make llm-hello`), `suggestions.py` (read-only list).
- `settings.parser_model_id` is `"fake"` when no model is called: use it for anything logged or
  stored, so fake output is never attributed to a real model.
- Handler order: Cognito access token (`app.auth.get_verifier()`, keys fetched from the internet,
  no `COGNITO_JWKS`) → 401; text > `parser_max_chars` (10,000) → 413 before any model call; bad
  body → 400; `AgendaParseError` → 422; `ModelBusyError` → 429; anything else → 503. Errors use
  the API's `{"error": {code, message, details}}` envelope. One JSON log line per parse
  (`agenda_parsed` / `agenda_parse_failed`) with user, provider, model, prompt version, chars,
  tokens, latency and `cost_usd`.
- Function `successfulsuccess-agenda-parser`: no VPC, 30 s, 512 MB, log group
  `/aws/lambda/successfulsuccess-agenda-parser` (7 days). Its function URL has `AuthType: NONE` and
  **CORS on the URL** (site origin + `http://localhost:3000`, POST) — unlike the API, whose CORS is in
  FastAPI. The handler must not add CORS headers. URL: `make aws-ai-url`.
- Saving: `PUT /api/v1/meetings/{id}/agenda` (`AgendaWrite`). A sent `ai_suggestion` must validate
  as `ParsedAgenda` and name its model and prompt version; it replaces the stored one. A save
  without one keeps the earlier suggestion. `ai_*` is never returned by the API; read it with
  `make aws-agendas` (invokes the API function with `{"action": "show-agendas"}`, read-only
  transaction, all users) or `make agendas-local`.
- Frontend: `components/agenda-dialog.tsx` (paste, Parse/Cancel with AbortController, per-status
  error messages, the agenda form with "suggested" badges), opened from the meeting details dialog.
  `NEXT_PUBLIC_PARSER_URL` is a build arg: `make aws-deploy-frontend` reads it from the Terraform
  output `parser_url`; compose takes `PARSER_URL` from `.env`. Empty hides Paste an agenda.
- Deploy order after backend changes: `make aws-deploy-backend` (push + migrate + new image on the
  builder and parser), then `make aws-deploy-frontend` if the parser URL or the UI changed.
  Switching models is `parser_provider` / `parser_model` in `infra/terraform.tfvars` and a push.
- Tests: `tests/test_agenda_parser.py`, `tests/test_agenda_lambda.py`, `tests/test_agenda_api.py`;
  no test calls a model (stub SDK clients, scripted providers, the fake provider).

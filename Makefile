COMPOSE ?= docker compose

# Windows: the recipes are POSIX shell, and native GNU make (winget install
# ezwinports.make) would hand them to cmd.exe. Run them with the bash, sed, awk,
# curl and friends that Git for Windows ships instead, whichever terminal make is
# started from. Installed Git elsewhere? make GIT_HOME="D:/Tools/Git" ...
# MSYS2/Cygwin make already has a POSIX shell, so it is left alone.
ifeq ($(OS),Windows_NT)
ifeq ($(findstring msys,$(MAKE_HOST))$(findstring cygwin,$(MAKE_HOST)),)
GIT_HOME ?= C:/Program Files/Git
export PATH := $(GIT_HOME)/bin;$(GIT_HOME)/usr/bin;$(PATH)
SHELL := bash.exe
.SHELLFLAGS := -c
endif
endif

# Local configuration (gitignored). These assignments beat variables exported in
# the shell, so override one on the command line instead: make aws-deploy-backend
# AWS_LAMBDA_ARCH=arm64
-include .env
# Every stack (ECR, Lambda, Aurora, S3 + CloudFront) is created in this one region.
AWS_REGION ?= us-east-1
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_REGION PROJECT_NAME
# On Windows, stop Git's bash rewriting container paths such as /aws or
# /dev/null into C:/Program Files/Git/... before docker sees them.
export MSYS_NO_PATHCONV := 1
export MSYS2_ARG_CONV_EXCL := *

# The AWS CLI runs in a container so nothing has to be installed on the host.
# The repository is mounted at /aws (the image's workdir) so the CLI can read
# infra/*.yml. Pass AWS=aws to use a CLI installed on the host instead.
AWS ?= docker run --rm \
	-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
	-e AWS_DEFAULT_REGION=$(AWS_REGION) \
	-v $(CURDIR):/aws -w /aws \
	amazon/aws-cli:latest

APP_STACK ?= $(PROJECT_NAME)-backend
ECR_STACK ?= $(PROJECT_NAME)-ecr
FRONTEND_STACK ?= $(PROJECT_NAME)-frontend
# Sign-in, the weekly report and the agenda parser are Terraform (infra/*.tf),
# applied only by HCP Terraform (workspace successfulsuccess-dev) after a push to
# main. Nothing here runs terraform apply; the targets below only read outputs
# and preview. Needs `terraform login` once and `make infra-init`.
TF ?= terraform
TF_DIR ?= infra
# The Terraform functions that run the backend image with another handler.
# Terraform ignores their image_uri: make aws-update-workers ships new code.
WORKER_FUNCTIONS ?= $(PROJECT_NAME)-report-builder $(PROJECT_NAME)-agenda-parser
IMAGE_TAG ?= latest
# The agenda parser's model (Lab 6): anthropic (Messages API on Bedrock), converse
# (Bedrock Converse API) or fake (no model). Try another one without editing .env:
# make llm-hello PARSER_PROVIDER=converse PARSER_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
PARSER_PROVIDER ?= anthropic
PARSER_MODEL ?= anthropic.claude-opus-5-5
# The parser runs in the backend container with the AWS credentials from .env;
# an empty AWS_SESSION_TOKEN is left out rather than passed as "".
PARSER_ENV = -e PARSER_PROVIDER="$(PARSER_PROVIDER)" -e PARSER_MODEL="$(PARSER_MODEL)" \
	-e PARSER_REGION="$(AWS_REGION)" \
	-e AWS_ACCESS_KEY_ID="$$AWS_ACCESS_KEY_ID" -e AWS_SECRET_ACCESS_KEY="$$AWS_SECRET_ACCESS_KEY" \
	$${AWS_SESSION_TOKEN:+-e AWS_SESSION_TOKEN="$$AWS_SESSION_TOKEN"} \
	$${ANTHROPIC_API_KEY:+-e ANTHROPIC_API_KEY}
# PARSER_PROVIDER=anthropic_api (the Claude API directly): locally the key comes
# from ANTHROPIC_API_KEY in .env, passed to the container by name only, so it is
# never on a command line. The deployed parser reads it from an SSM SecureString.
export ANTHROPIC_API_KEY
# x86_64 or arm64. arm64 is ~20% cheaper on Lambda and builds natively on
# Apple Silicon; the image platform is derived from it so the two cannot drift.
AWS_LAMBDA_ARCH ?= x86_64
IMAGE_PLATFORM = $(if $(filter arm64,$(AWS_LAMBDA_ARCH)),linux/arm64,linux/amd64)
# Every stack carries this tag, and CloudFormation copies it onto each resource
# that supports tags, so Cost Explorer and Resource Groups can find the project.
STACK_TAGS = --tags "PROJECT_NAME=$(PROJECT_NAME)"

# infra/certificate.sh reuses the CLI configured above. CloudFront only reads
# certificates from us-east-1, so that is where the frontend's goes.
CERT = AWS_CLI="$(AWS)" AWS_CERT_REGION=us-east-1 infra/certificate.sh

# $(call stack-output,<stack>,<output key>)
stack-output = $(AWS) cloudformation describe-stacks --stack-name $(1) \
	--query 'Stacks[0].Outputs[?OutputKey==`$(2)`].OutputValue' --output text

# $(call tf-output,<output name>): one output of the Terraform config (infra/outputs.tf)
tf-output = $(TF) -chdir=$(TF_DIR) output -raw $(1)

# CloudFormation refuses to update a stack that is still busy, and a Lambda in a
# VPC can keep one in *_CLEANUP_IN_PROGRESS for ~20 minutes while its network
# interfaces are released. Wait that out instead of failing.
# $(call wait-stack-idle,<stack>)
# REVIEW_IN_PROGRESS means a changeset exists but was never executed (e.g. a
# previous deploy was interrupted). It will never self-resolve, so skip it here
# and let clear-failed-create handle it below.
wait-stack-idle = while status=$$($(AWS) cloudformation describe-stacks --stack-name $(1) \
		--query 'Stacks[0].StackStatus' --output text 2>/dev/null | tr -d '[:space:]'); \
		case "$$status" in REVIEW_IN_PROGRESS|*_COMPLETE|*_FAILED|"") false ;; *_IN_PROGRESS) true ;; *) false ;; esac; do \
		echo "$(1) is $$status — waiting for it to settle..."; sleep 30; done

# A stack whose first create failed (ROLLBACK_COMPLETE) or whose changeset was
# never executed (REVIEW_IN_PROGRESS) must be deleted before CloudFormation
# can deploy fresh. Neither holds resources, so it is safe to remove.
# $(call clear-failed-create,<stack>)
clear-failed-create = status=$$($(AWS) cloudformation describe-stacks --stack-name $(1) \
		--query 'Stacks[0].StackStatus' --output text 2>/dev/null | tr -d '[:space:]'); \
		case "$$status" in ROLLBACK_COMPLETE|REVIEW_IN_PROGRESS) \
		echo "$(1) is in $$status — deleting it before retrying"; \
		$(AWS) cloudformation delete-stack --stack-name $(1) && \
		$(AWS) cloudformation wait stack-delete-complete --stack-name $(1) ;; esac

# Fail early and clearly when .env has no credentials in it.
define require-aws-credentials
	@test -n "$(AWS_ACCESS_KEY_ID)" -a -n "$(AWS_SECRET_ACCESS_KEY)" || { \
		echo "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are empty — set them in .env"; \
		exit 1; }
endef

# Pin every worker function on the pushed image by digest (as the stacks did),
# wait until Lambda has switched, and print the digest each one now runs.
define update-workers
	@repo=$$($(call stack-output,$(ECR_STACK),RepositoryUri) | tr -d '[:space:]'); \
		digest=$$($(AWS) ecr describe-images --repository-name "$${repo#*/}" \
			--image-ids imageTag=$(IMAGE_TAG) --query 'imageDetails[0].imageDigest' \
			--output text | tr -d '[:space:]'); \
		case "$$digest" in sha256:*) ;; *) echo "No $(IMAGE_TAG) image in $$repo — run: make aws-push"; exit 1 ;; esac; \
		for fn in $(WORKER_FUNCTIONS); do \
			echo "Updating $$fn to $$repo@$$digest"; \
			$(AWS) lambda update-function-code --function-name "$$fn" \
				--image-uri "$$repo@$$digest" --query LastUpdateStatus --output text >/dev/null || exit 1; \
			$(AWS) lambda wait function-updated --function-name "$$fn" || exit 1; \
		done; \
		for fn in $(WORKER_FUNCTIONS); do \
			uri=$$($(AWS) lambda get-function --function-name "$$fn" \
				--query Code.ResolvedImageUri --output text | tr -d '[:space:]'); \
			printf '%-40s %s\n' "$$fn" "$${uri##*@}"; \
		done
endef

define require-db-password
	@test -n "$(AWS_DB_PASSWORD)" || { \
		echo "AWS_DB_PASSWORD is empty — set it in .env (8+ chars, [A-Za-z0-9_-] only)"; \
		exit 1; }
endef

.PHONY: help up up-build down down-v logs ps migrate revision seed seed-weeks report-local test lint fmt shell-backend psql \
        llm-hello parse agendas-local aws-agendas \
        aws-whoami aws-deploy aws-auth-env aws-ecr aws-push aws-deploy-backend aws-update-workers aws-migrate aws-url aws-status aws-logs \
        aws-frontend-cert aws-deploy-frontend aws-frontend-url report-now dlq-status \
        aws-ai-url aws-logs-ai \
        infra-init infra-fmt infra-validate infra-plan \
        aws-destroy

help:
	@grep -hE '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start the whole stack
	$(COMPOSE) up

up-build: ## Rebuild images and start the whole stack
	$(COMPOSE) up --build

down: ## Stop the stack
	$(COMPOSE) down

down-v: ## Stop the stack and delete the database volume
	$(COMPOSE) down -v

logs: ## Follow logs from every service
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Apply database migrations
	$(COMPOSE) exec backend alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add column"
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

seed: ## Insert demo meetings for today for one user: make seed owner=<cognito-sub>
	@test -n "$(owner)" || { echo "Usage: make seed owner=<cognito-sub> (the user's sub from the Cognito console)"; exit 1; }
	$(COMPOSE) exec backend python -m app.seed "$(owner)"

seed-weeks: ## Insert ~15 demo meetings over the last two ISO weeks, for the weekly report (once)
	$(COMPOSE) exec backend python -m app.reports.seed_weeks

report-local: ## Print one week's report from the local database: make report-local WEEK=2026-W41
	@test -n "$(WEEK)" || { echo "Usage: make report-local WEEK=2026-W41 (an ISO week)"; exit 1; }
	@$(COMPOSE) exec -T backend python -m app.reports "$(WEEK)"

llm-hello: ## Ask the parser model one question; prints the answer, stop_reason and usage
	$(require-aws-credentials)
	@$(COMPOSE) exec -T $(PARSER_ENV) backend python -m app.ai.hello

# The text goes in on stdin, so quotes and Cyrillic survive. FILE= reads a file
# instead (UTF-8), which is easier for multi-line emails.
parse: ## Parse pasted text into an agenda: make parse TEXT="..." (or FILE=agenda.txt)
	@if [ -n "$(FILE)" ]; then cat "$(FILE)"; else printf '%s' '$(subst ','\'',$(TEXT))'; fi \
		| $(COMPOSE) exec -T $(PARSER_ENV) backend python -m app.ai.agenda

agendas-local: ## Show the latest saved agendas next to their AI suggestion, from the local database
	@$(COMPOSE) exec -T backend python -m app.ai.suggestions $(or $(LIMIT),5)

test: ## Run the backend test suite against a throwaway database
	$(COMPOSE) exec db psql -U app -d postgres -tc \
		"SELECT 1 FROM pg_database WHERE datname='meetings_test'" | grep -q 1 || \
		$(COMPOSE) exec db createdb -U app meetings_test
	$(COMPOSE) exec -e DATABASE_URL=postgresql+asyncpg://app:app@db:5432/meetings_test backend pytest -q

lint: ## Lint backend and frontend
	$(COMPOSE) exec backend ruff check .
	$(COMPOSE) exec frontend npm run lint

fmt: ## Format the backend code
	$(COMPOSE) exec backend ruff format .

shell-backend: ## Open a shell in the backend container
	$(COMPOSE) exec backend sh

psql: ## Open psql against the application database
	$(COMPOSE) exec db psql -U app -d meetings

aws-whoami: ## Verify the AWS credentials in .env
	$(require-aws-credentials)
	$(AWS) sts get-caller-identity

aws-deploy: ## Deploy the backend, then the frontend built against it (sign-in, reports, parser: HCP Terraform)
	@$(MAKE) --no-print-directory aws-deploy-backend
	@$(MAKE) --no-print-directory aws-deploy-frontend

aws-auth-env: ## Print the Cognito settings to put in .env for local development
	@for pair in COGNITO_USER_POOL_ID:user_pool_id COGNITO_CLIENT_ID:user_pool_client_id \
			COGNITO_DOMAIN:hosted_domain COGNITO_GOOGLE_ENABLED:google_enabled; do \
		value=$$($(call tf-output,$${pair#*:})) || exit 1; \
		echo "$${pair%%:*}=$$value"; \
	done

aws-ecr: ## Create the ECR repository for the backend image
	$(require-aws-credentials)
	$(AWS) cloudformation deploy \
		--stack-name $(ECR_STACK) \
		--template-file infra/ecr.yml \
		--no-fail-on-empty-changeset \
		$(STACK_TAGS) \
		--parameter-overrides "ProjectName=$(PROJECT_NAME)"

aws-push: aws-ecr ## Build the backend Lambda image and push it to ECR
	$(require-aws-credentials)
	@repo=$$($(call stack-output,$(ECR_STACK),RepositoryUri) | tr -d '[:space:]'); \
		echo "Pushing $$repo:$(IMAGE_TAG) ($(IMAGE_PLATFORM))"; \
		$(AWS) ecr get-login-password | docker login --username AWS --password-stdin "$${repo%%/*}"; \
		docker build --platform $(IMAGE_PLATFORM) --provenance=false \
			-f backend/Dockerfile.lambda -t "$$repo:$(IMAGE_TAG)" ./backend; \
		docker push "$$repo:$(IMAGE_TAG)"

aws-deploy-backend: aws-push ## Deploy the backend to AWS (Lambda function URL + RDS), migrate, then update the worker functions
	$(require-aws-credentials)
	$(require-db-password)
	@pool=$$($(call tf-output,user_pool_id) 2>/dev/null | tr -d '[:space:]'); \
		test -n "$$pool" || { echo "No user_pool_id Terraform output — run make infra-init (and terraform login)"; exit 1; }; \
		client=$$($(call tf-output,user_pool_client_id) | tr -d '[:space:]'); \
		issuer=$$($(call tf-output,issuer) | tr -d '[:space:]'); \
		jwks=$$(curl -fsS "$$issuer/.well-known/jwks.json" | base64 | tr -d '\n'); \
		test -n "$$jwks" || { echo "Could not download $$issuer/.well-known/jwks.json"; exit 1; }; \
		vpc=$$($(AWS) ec2 describe-vpcs --filters Name=isDefault,Values=true \
		--query 'Vpcs[0].VpcId' --output text | tr -d '[:space:]'); \
		test "$$vpc" != "None" -a -n "$$vpc" || { \
			echo "No default VPC in $(AWS_REGION) — pass VpcId/SubnetIds yourself"; exit 1; }; \
		subnets=$$($(AWS) ec2 describe-subnets \
			--filters Name=vpc-id,Values=$$vpc Name=default-for-az,Values=true \
			--query 'Subnets[].SubnetId' --output text | tr '[:space:]' ',' | sed 's/,*$$//'); \
		repo=$$($(call stack-output,$(ECR_STACK),RepositoryUri) | tr -d '[:space:]'); \
		digest=$$($(AWS) ecr describe-images --repository-name "$${repo#*/}" \
			--image-ids imageTag=$(IMAGE_TAG) --query 'imageDetails[0].imageDigest' \
			--output text | tr -d '[:space:]'); \
		cors="$(AWS_CORS_ORIGINS)"; \
		if [ -z "$$cors" ]; then \
			cors=$$($(call stack-output,$(FRONTEND_STACK),AllowedOrigins) 2>/dev/null | tr -d '[:space:]'); \
			case "$$cors" in ""|None) cors='*' ;; esac; \
		fi; \
		echo "vpc=$$vpc subnets=$$subnets image=$$repo@$$digest cors=$$cors"; \
		echo "This takes ~15 minutes the first time (Aurora is the slow part)."; \
		$(call wait-stack-idle,$(APP_STACK)); \
		$(call clear-failed-create,$(APP_STACK)); \
		$(AWS) cloudformation deploy \
			--stack-name $(APP_STACK) \
			--template-file infra/backend.yml \
			--capabilities CAPABILITY_IAM \
			--no-fail-on-empty-changeset \
			$(STACK_TAGS) \
			--parameter-overrides \
				"ProjectName=$(PROJECT_NAME)" \
				"VpcId=$$vpc" \
				"SubnetIds=$$subnets" \
				ImageUri="$$repo@$$digest" \
				"Architecture=$(AWS_LAMBDA_ARCH)" \
				"DbPassword=$(AWS_DB_PASSWORD)" \
				"AppTimezone=$(APP_TIMEZONE)" \
				"CorsOrigins=$$cors" \
				"CognitoUserPoolId=$$pool" \
				"CognitoClientId=$$client" \
				"CognitoJwks=$$jwks"
	@$(MAKE) --no-print-directory aws-migrate
	@# The same pushed image, now that the schema matches it.
	$(update-workers)
	@$(MAKE) --no-print-directory aws-url

aws-update-workers: aws-push ## Ship the pushed image to the report builder and the agenda parser (Terraform ignores their image)
	$(require-aws-credentials)
	$(update-workers)

aws-migrate: ## Apply database migrations (invokes the backend function directly)
	@fn=$$($(call stack-output,$(APP_STACK),FunctionName) | tr -d '[:space:]'); \
		echo "Migrating ($$fn)"; \
		err=$$($(AWS) lambda invoke --function-name "$$fn" \
			--cli-binary-format raw-in-base64-out --payload '{"action":"migrate"}' \
			--query FunctionError --output text /dev/null | tr -d '[:space:]'); \
		test "$$err" = "None" || { echo "Migration failed ($$err) — see make aws-logs"; exit 1; }

# RDS has no public access, so the API function reads them (read-only). Lambda
# returns the JSON with \u escapes; Python, when there is one, makes it readable.
aws-agendas: ## Show the latest saved agendas next to their AI suggestion, from RDS: make aws-agendas LIMIT=5
	$(require-aws-credentials)
	@fn=$$($(call stack-output,$(APP_STACK),FunctionName) | tr -d '[:space:]'); \
		out=.aws-agendas.json; \
		err=$$($(AWS) lambda invoke --function-name "$$fn" \
			--cli-binary-format raw-in-base64-out \
			--payload '{"action":"show-agendas","limit":$(or $(LIMIT),5)}' \
			--query FunctionError --output text "$$out" | tr -d '[:space:]'); \
		if [ "$$err" != "None" ]; then cat "$$out"; rm -f "$$out"; echo; \
			echo "Failed ($$err) — see make aws-logs"; exit 1; fi; \
		PYTHONIOENCODING=utf-8 python -m json.tool --no-ensure-ascii "$$out" 2>/dev/null || cat "$$out"; \
		rm -f "$$out"

aws-url: ## Print the deployed API URL
	@$(call stack-output,$(APP_STACK),ApiUrl)

aws-status: ## Show the stack outputs and the API function's state
	@$(AWS) cloudformation describe-stacks --stack-name $(APP_STACK) \
		--query 'Stacks[0].Outputs' --output table
	@fn=$$($(call stack-output,$(APP_STACK),FunctionName) | tr -d '[:space:]'); \
		$(AWS) lambda get-function-configuration --function-name "$$fn" \
			--query '{state:State,lastUpdate:LastUpdateStatus,arch:Architectures[0],memory:MemorySize}' \
			--output table

aws-logs: ## Follow the backend function logs
	$(AWS) logs tail /aws/lambda/$(PROJECT_NAME)-backend --follow

aws-frontend-cert: ## Request and validate the HTTPS certificate for AWS_FRONTEND_DOMAIN (in us-east-1)
	$(require-aws-credentials)
	@test -n "$(AWS_FRONTEND_DOMAIN)" || { \
		echo "AWS_FRONTEND_DOMAIN is empty — set it in .env (e.g. app.example.com)"; exit 1; }
	@$(CERT) ensure "$(AWS_FRONTEND_DOMAIN)"

aws-deploy-frontend: ## Deploy the frontend to S3 + CloudFront, built against the deployed backend URL
	$(require-aws-credentials)
	@api=$$($(call stack-output,$(APP_STACK),ApiUrl) 2>/dev/null | tr -d '[:space:]'); \
		test -n "$$api" -a "$$api" != "None" || { \
			echo "No backend API found — run: make aws-deploy-backend"; exit 1; }; \
		domain=""; \
		if [ -n "$(AWS_FRONTEND_DOMAIN)" ]; then \
			cert=$$($(CERT) find "$(AWS_FRONTEND_DOMAIN)"); \
			test -n "$$cert" || { \
				echo "No issued us-east-1 certificate for $(AWS_FRONTEND_DOMAIN) — run: make aws-frontend-cert"; \
				exit 1; }; \
			zone=$$($(CERT) zone "$(AWS_FRONTEND_DOMAIN)"); \
			domain="DomainName=$(AWS_FRONTEND_DOMAIN) CertificateArn=$$cert HostedZoneId=$$zone"; \
			echo "custom domain: $(AWS_FRONTEND_DOMAIN) (Route 53 zone: $${zone:-none})"; \
		fi; \
		$(call wait-stack-idle,$(FRONTEND_STACK)); \
		$(call clear-failed-create,$(FRONTEND_STACK)); \
		echo "A new CloudFront distribution takes ~5 minutes to come up."; \
		$(AWS) cloudformation deploy \
			--stack-name $(FRONTEND_STACK) \
			--template-file infra/frontend.yml \
			--no-fail-on-empty-changeset \
			$(STACK_TAGS) \
			--parameter-overrides \
				"ProjectName=$(PROJECT_NAME)" \
				"PricingPlan=$(or $(AWS_CLOUDFRONT_PLAN),FREE)" \
				$$domain
	@# Cognito's callback URLs follow the site's URL in Terraform (auth.tf reads
	@# this stack's DistributionDomain): a new distribution needs a Terraform run.
	@api=$$($(call stack-output,$(APP_STACK),ApiUrl) | tr -d '[:space:]'); \
		tf_out() { $(call tf-output,$$1) 2>/dev/null | tr -d '[:space:]'; }; \
		pool=$$(tf_out user_pool_id); \
		test -n "$$pool" || echo "No Terraform outputs (make infra-init?) — building without sign-in"; \
		bucket=$$($(call stack-output,$(FRONTEND_STACK),BucketName) | tr -d '[:space:]'); \
		dist=$$($(call stack-output,$(FRONTEND_STACK),DistributionId) | tr -d '[:space:]'); \
		parser=$$(tf_out parser_url); \
		test -n "$$parser" || echo "No agenda parser — building without Paste an agenda"; \
		echo "Building the static export against $$api"; \
		rm -rf frontend/out; \
		docker build --target export --output type=local,dest=frontend/out \
			--build-arg NEXT_PUBLIC_API_BASE_URL="$$api" \
			--build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID="$$pool" \
			--build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID="$$(tf_out user_pool_client_id)" \
			--build-arg NEXT_PUBLIC_COGNITO_DOMAIN="$$(tf_out hosted_domain)" \
			--build-arg NEXT_PUBLIC_COGNITO_GOOGLE_ENABLED="$$(tf_out google_enabled)" \
			--build-arg NEXT_PUBLIC_PARSER_URL="$$parser" \
			./frontend || exit 1; \
		echo "Uploading to s3://$$bucket"; \
		$(AWS) s3 sync frontend/out "s3://$$bucket" --delete --exclude "*.html" \
			--cache-control "public,max-age=31536000,immutable" --only-show-errors || exit 1; \
		$(AWS) s3 sync frontend/out "s3://$$bucket" --delete --exclude "*" --include "*.html" \
			--cache-control "no-cache" --only-show-errors || exit 1; \
		$(AWS) cloudfront create-invalidation --distribution-id "$$dist" --paths "/*" \
			--query 'Invalidation.Status' --output text
	@$(MAKE) --no-print-directory aws-frontend-url
	@if [ -z "$(AWS_CORS_ORIGINS)" ]; then \
		allowed=$$($(call stack-output,$(FRONTEND_STACK),AllowedOrigins) | tr -d '[:space:]'); \
		fn=$$($(call stack-output,$(APP_STACK),FunctionName) | tr -d '[:space:]'); \
		current=$$($(AWS) lambda get-function-configuration --function-name "$$fn" \
			--query 'Environment.Variables.CORS_ORIGINS' --output text | tr -d '[:space:]'); \
		test "$$current" = "$$allowed" || echo "The API still allows CORS_ORIGINS=$$current — run make aws-deploy-backend to limit it to $$allowed"; \
	fi
	@if [ -n "$(AWS_FRONTEND_DOMAIN)" ] && [ -z "$$($(CERT) zone "$(AWS_FRONTEND_DOMAIN)")" ]; then \
		echo "Point $(AWS_FRONTEND_DOMAIN) at the distribution: CNAME $$($(call stack-output,$(FRONTEND_STACK),DistributionDomain) | tr -d '[:space:]')"; \
	fi

aws-frontend-url: ## Print the deployed site URL
	@$(call stack-output,$(FRONTEND_STACK),SiteUrl)

report-now: ## Queue a report for one week: make report-now WEEK=2026-W40
	@printf '%s' "$(WEEK)" | grep -Eqx '[0-9]{4}-W[0-9]{2}' || { \
		echo "Usage: make report-now WEEK=2026-W40 (an ISO week, YYYY-Www)"; exit 1; }
	@url=$$($(call tf-output,queue_url) 2>/dev/null | tr -d '[:space:]'); \
		test -n "$$url" || { echo "No queue_url Terraform output — run make infra-init (and terraform login)"; exit 1; }; \
		id=$$($(AWS) sqs send-message --queue-url "$$url" \
			--message-body '{"week":"$(WEEK)","source":"manual"}' \
			--query MessageId --output text | tr -d '[:space:]') || exit 1; \
		echo "Queued $(WEEK): MessageId $$id"

dlq-status: ## Show how many messages wait in the report queue and its dead-letter queue
	@for key in queue_url dlq_url; do \
			url=$$($(call tf-output,$$key) 2>/dev/null | tr -d '[:space:]'); \
			test -n "$$url" || { echo "No $$key Terraform output — run make infra-init (and terraform login)"; exit 1; }; \
			counts=$$($(AWS) sqs get-queue-attributes --queue-url "$$url" \
				--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
				--query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' \
				--output text | tr -d '\r'); \
			set -- $$counts; \
			printf '%-55s waiting=%s in-flight=%s\n' "$${url##*/}" "$$1" "$$2"; \
		done

aws-ai-url: ## Print the agenda parser's URL
	@$(call tf-output,parser_url); echo

aws-logs-ai: ## Follow the agenda parser's logs (one JSON line per parse)
	$(AWS) logs tail /aws/lambda/$(PROJECT_NAME)-agenda-parser --follow

# --- Terraform (auth, reports, ai) -------------------------------------------
# Local preview only: HCP Terraform applies after a push to main.

infra-init: ## Connect infra/ to the HCP Terraform workspace (run terraform login once first)
	$(TF) -chdir=$(TF_DIR) init

infra-fmt: ## Format the Terraform files in infra/
	$(TF) -chdir=$(TF_DIR) fmt

infra-validate: ## Check the Terraform configuration in infra/
	$(TF) -chdir=$(TF_DIR) validate

infra-plan: ## Preview what HCP Terraform would change (never applies)
	$(TF) -chdir=$(TF_DIR) plan -input=false

aws-destroy: ## Delete the CloudFormation stacks, including the database and its data
	$(require-aws-credentials)
	@# The report builder runs in the backend's subnets with its security group,
	@# so the Terraform resources go first, through a destroy run in HCP Terraform.
	@if $(call tf-output,builder_function_name) >/dev/null 2>&1; then \
		echo "Terraform still manages sign-in, reports and the parser — queue a destroy run in HCP Terraform first"; \
		exit 1; fi
	@printf 'Delete %s, %s and %s? The database and all its data go with them (no snapshot). Type yes: ' \
		"$(FRONTEND_STACK)" "$(APP_STACK)" "$(ECR_STACK)"; \
		read answer; test "$$answer" = "yes" || { echo "Aborted."; exit 1; }
	@bucket=$$($(call stack-output,$(FRONTEND_STACK),BucketName) 2>/dev/null | tr -d '[:space:]'); \
		if [ -n "$$bucket" ] && [ "$$bucket" != "None" ]; then \
			echo "Emptying s3://$$bucket"; \
			$(AWS) s3 rm "s3://$$bucket" --recursive --only-show-errors || true; \
		fi
	-$(AWS) cloudformation delete-stack --stack-name $(FRONTEND_STACK)
	-$(AWS) cloudformation wait stack-delete-complete --stack-name $(FRONTEND_STACK)
	@echo "Deleting $(APP_STACK) — Lambda releases its VPC network interfaces slowly, allow ~20 minutes."
	$(AWS) cloudformation delete-stack --stack-name $(APP_STACK)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(APP_STACK)
	$(AWS) cloudformation delete-stack --stack-name $(ECR_STACK)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(ECR_STACK)
	@echo "All CloudFormation stacks deleted."

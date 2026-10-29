# CloudFormation → Terraform: inventory (Lab 7)

Read-only snapshot taken on 2026-10-29 with `describe-stacks`, `describe-stack-resources` and a few
`describe-*`/`get-*` calls (security group rules, Lambda policies, schedule group, VPC endpoint).
Account `980553487282`, region **us-east-1**, provider `hashicorp/aws ~> 6.0`. Nothing in AWS was
changed.

Six stacks, all named in the `Makefile` (`$(PROJECT_NAME)-<suffix>`), all tagged
`PROJECT_NAME=successfulsuccess`:

| Variable | Stack | Template | Status | Last change |
| --- | --- | --- | --- | --- |
| `ECR_STACK` | `successfulsuccess-ecr` | `infra/ecr.yml` | UPDATE_COMPLETE | 2026-10-13 |
| `AUTH_STACK` | `successfulsuccess-auth` | `infra/auth.yml` | UPDATE_COMPLETE | 2026-10-08 |
| `APP_STACK` | `successfulsuccess-backend` | `infra/backend.yml` | UPDATE_COMPLETE | 2026-10-27 |
| `FRONTEND_STACK` | `successfulsuccess-frontend` | `infra/frontend.yml` | CREATE_COMPLETE | 2026-09-30 |
| `REPORTS_STACK` | `successfulsuccess-reports` | `infra/reports.yml` | UPDATE_COMPLETE | 2026-10-14 |
| `AI_STACK` | `successfulsuccess-ai` | `infra/ai.yml` | UPDATE_COMPLETE | 2026-10-28 |

## Scope

Only **auth**, **reports** and **ai** move to Terraform (`infra/*.tf`, HCP Terraform workspace
`successfulsuccess-dev`). **ecr**, **backend** and **frontend** stay in CloudFormation: Terraform
reads them with `data "aws_cloudformation_stack"` and never manages their resources. Their tables
below are kept for reference only and are not part of the import.

What Terraform reads from the stacks that stay:

| Data source | Read | Used for |
| --- | --- | --- |
| `data.aws_cloudformation_stack.ecr` | output `RepositoryUri` | `image_uri` of a function created from scratch |
| `data.aws_cloudformation_stack.backend` | outputs `FunctionName`, `DatabaseEndpoint`; parameters `DbUsername`, `DbName` | the builder's `DATABASE_URL`; finding the API function |
| `data.aws_lambda_function.api` | `vpc_config` (VPC, subnets, security group) | the builder's `vpc_config` and the S3 endpoint's VPC |
| `data.aws_cloudformation_stack.frontend` | output `DistributionDomain` | Cognito callback/logout URLs, the parser URL's CORS origins |

In scope: **26 CloudFormation resources → 40 Terraform resources = 26 imported + 14 created**.
Every CloudFormation resource in scope is imported (one `import` block each); the 14 created
resources are the child configuration documents (inline IAM policies, managed policy attachments,
S3 bucket settings) described below. `RecipientIdentity` was never deployed and stays at
`count = 0`. The `import` blocks are written after the three stacks are deleted with
`DeletionPolicy: Retain`. Counts per stack: [Resource count per stack](#resource-count-per-stack).

Placeholders used below instead of personal values: `<REPORT_SENDER>` (the `REPORT_SENDER` address
in `.env`; `REPORT_RECIPIENT` is the same address, so no second identity exists) and
`<GOOGLE_CLIENT_ID>` (`GOOGLE_CLIENT_ID` in `.env`).

## How to read the resource tables

- One row per Terraform resource. A CloudFormation resource whose properties Terraform models as
  separate resources (S3 bucket settings, IAM inline policies, ECR policies, security group rules)
  gets extra rows marked **child**, with LogicalId `↳ <parent>` and no PhysicalId of its own.
- **Decision**: **Import** = bring the existing object into state with an `import` block.
  **Create** = let Terraform create it on the first apply.
- The decisions assume the hand-over most labs use: every resource first gets
  `DeletionPolicy: Retain`, the stack is then deleted (so CloudFormation lets go of everything and
  deletes nothing), and Terraform takes over. "Create" is only chosen for objects that are a
  **single configuration document attached to a parent** (a bucket's encryption, a role's inline
  policy, a repository's lifecycle policy, ...). The AWS call behind those is a PUT that replaces
  the document; Terraform writes back the same JSON, so there is no gap, no duplicate and no new
  identity. Importing them as well is equally fine; it only costs more `import` blocks.
- Everything that has an identity of its own (a name, an id or a URL other things point at), or
  whose creation would fail or duplicate, is **Import**.

### successfulsuccess-ecr (1 CFN resource → 3 Terraform resources)

**Out of scope: stays in CloudFormation** (read with `data "aws_cloudformation_stack" "ecr"`).

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| ecr | `Repository` | `AWS::ECR::Repository` | `successfulsuccess-backend` | `aws_ecr_repository` | `successfulsuccess-backend` | **Import**: holds every image; the functions are pinned to digests in it. Set `force_delete = true` (= `EmptyOnDelete`). |
| ecr | ↳ Repository (child) | `RepositoryPolicyText` | — | `aws_ecr_repository_policy` | `successfulsuccess-backend` | **Create**: `SetRepositoryPolicy` replaces the one policy with the same JSON. |
| ecr | ↳ Repository (child) | `LifecyclePolicy` | — | `aws_ecr_lifecycle_policy` | `successfulsuccess-backend` | **Create**: `PutLifecyclePolicy` replaces it; same rule (keep 15). |

### successfulsuccess-auth (5 → 5)

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| auth | `UserPool` | `AWS::Cognito::UserPool` | `us-east-1_xgnKmaDDO` | `aws_cognito_user_pool` | `us-east-1_xgnKmaDDO` | **Import**: holds every user account; re-creating loses them and changes every `sub`. |
| auth | `UserPoolClient` | `AWS::Cognito::UserPoolClient` | `7kbe5h0m3qbr70us2niiumqc15` | `aws_cognito_user_pool_client` | `us-east-1_xgnKmaDDO/7kbe5h0m3qbr70us2niiumqc15` | **Import**: a new client gets a new id, which the frontend build, the API and the parser all check tokens against. |
| auth | `UserPoolDomain` | `AWS::Cognito::UserPoolDomain` | `kvasovets` | `aws_cognito_user_pool_domain` | `kvasovets` | **Import**: the domain name is taken (by this pool), so a create fails; it is also in Google's redirect URI. |
| auth | `GoogleIdentityProvider` (child) | `AWS::Cognito::UserPoolIdentityProvider` | `Google` | `aws_cognito_identity_provider` | `us-east-1_xgnKmaDDO:Google` | **Import**: a second `Google` provider is refused ("already exists"). Import reads `client_secret` into state. |
| auth | `ManagedLoginBranding` (child) | `AWS::Cognito::ManagedLoginBranding` | `us-east-1_xgnKmaDDO\|279ee64a-fd6f-4074-a197-98947dbf61a8` | `aws_cognito_managed_login_branding` | `us-east-1_xgnKmaDDO,279ee64a-fd6f-4074-a197-98947dbf61a8` | **Import**: one branding per client; a create is refused. Note the separator: `\|` in CFN, `,` in Terraform (check the resource's Import section when writing the block). |

### successfulsuccess-backend (10 → 14)

**Out of scope: stays in CloudFormation** (read with `data "aws_cloudformation_stack" "backend"`).

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| backend | `FunctionSecurityGroup` | `AWS::EC2::SecurityGroup` | `sg-06b7e429066e1c5f3` | `aws_security_group` | `sg-06b7e429066e1c5f3` | **Import**: the DB rule and the report builder reference this id. |
| backend | ↳ FunctionSecurityGroup (child) | egress (CFN default) | `sgr-0f6f9855ff4fcab62` | `aws_vpc_security_group_egress_rule` | `sgr-0f6f9855ff4fcab62` | **Import**: allow-all egress CloudFormation added by default. A create fails as a duplicate rule; leaving it out of config leaves it unmanaged. |
| backend | `DbSecurityGroup` | `AWS::EC2::SecurityGroup` | `sg-050a697dbe192fd34` | `aws_security_group` | `sg-050a697dbe192fd34` | **Import**: attached to the DB instance; replacing it means modifying the instance. |
| backend | ↳ DbSecurityGroup (child) | `SecurityGroupIngress` | `sgr-0d66f0ecc5f8b214b` | `aws_vpc_security_group_ingress_rule` | `sgr-0d66f0ecc5f8b214b` | **Import**: tcp 5432 from `sg-06b7e429066e1c5f3`. A create fails with `InvalidPermission.Duplicate`. |
| backend | ↳ DbSecurityGroup (child) | egress (CFN default) | `sgr-0d1848f895a355a67` | `aws_vpc_security_group_egress_rule` | `sgr-0d1848f895a355a67` | **Import**: same reason as the function SG's egress rule. |
| backend | `DbSubnetGroup` | `AWS::RDS::DBSubnetGroup` | `successfulsuccess-backend-dbsubnetgroup-sbjvliyslsdm` | `aws_db_subnet_group` | `successfulsuccess-backend-dbsubnetgroup-sbjvliyslsdm` | **Import**: a different name forces replacing the DB instance. Keep the CFN-generated `name`. |
| backend | `DbInstance` | `AWS::RDS::DBInstance` | `successfulsuccess-db` | `aws_db_instance` | `successfulsuccess-db` | **Import**: the data. The password is never read on import; give it as `password_wo` (or accept one in-place `ModifyDBInstance` with the same value). Set `skip_final_snapshot` to match today's behaviour. |
| backend | `FunctionRole` | `AWS::IAM::Role` | `successfulsuccess-backend-FunctionRole-01NooiWHoXCK` | `aws_iam_role` | `successfulsuccess-backend-FunctionRole-01NooiWHoXCK` | **Import**: a name change forces a new role. Keep the generated name. |
| backend | ↳ FunctionRole (child) | `ManagedPolicyArns` | — | `aws_iam_role_policy_attachment` | `successfulsuccess-backend-FunctionRole-01NooiWHoXCK/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole` | **Create**: `AttachRolePolicy` for a policy that is already attached is a no-op. |
| backend | `LogGroup` | `AWS::Logs::LogGroup` | `/aws/lambda/successfulsuccess-backend` | `aws_cloudwatch_log_group` | `/aws/lambda/successfulsuccess-backend` | **Import**: a create fails (`ResourceAlreadyExistsException`). |
| backend | `ApiFunction` | `AWS::Lambda::Function` | `successfulsuccess-backend` | `aws_lambda_function` | `successfulsuccess-backend` | **Import**: the API. Its env holds `DATABASE_URL` with the password, so state is sensitive. |
| backend | `FunctionUrl` | `AWS::Lambda::Url` | `arn:aws:lambda:us-east-1:980553487282:function:successfulsuccess-backend` | `aws_lambda_function_url` | `successfulsuccess-backend` | **Import**: a re-created URL gets a new host, which is baked into the frontend build. |
| backend | `FunctionUrlPermission` (child) | `AWS::Lambda::Permission` | `successfulsuccess-backend-FunctionUrlPermission-Ha6kFrd4KD0d` | `aws_lambda_permission` | `successfulsuccess-backend/successfulsuccess-backend-FunctionUrlPermission-Ha6kFrd4KD0d` | **Import**: a create adds a second public statement next to the retained one, which would then be unmanaged. Keep `statement_id` = the current Sid. |
| backend | `FunctionUrlInvokePermission` (child) | `AWS::Lambda::Permission` | `successfulsuccess-backend-FunctionUrlInvokePermission-yx3QAB01TpaZ` | `aws_lambda_permission` | `successfulsuccess-backend/successfulsuccess-backend-FunctionUrlInvokePermission-yx3QAB01TpaZ` | **Import**: same reason. |

### successfulsuccess-frontend (6 → 9)

**Out of scope: stays in CloudFormation** (read with `data "aws_cloudformation_stack" "frontend"`).

Not deployed because their conditions are false: `PricingPlanSubscription` (`PricingPlan=PAY_AS_YOU_GO`),
`AliasRecord` and `AliasRecordIpv6` (no `DomainName`/`HostedZoneId`).

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| frontend | `Bucket` | `AWS::S3::Bucket` | `successfulsuccess-frontend-980553487282` | `aws_s3_bucket` | `successfulsuccess-frontend-980553487282` | **Import**: bucket names are global; a create fails. |
| frontend | ↳ Bucket (child) | `PublicAccessBlockConfiguration` | — | `aws_s3_bucket_public_access_block` | `successfulsuccess-frontend-980553487282` | **Create**: `PutPublicAccessBlock`, same four `true`s. |
| frontend | ↳ Bucket (child) | `OwnershipControls` | — | `aws_s3_bucket_ownership_controls` | `successfulsuccess-frontend-980553487282` | **Create**: `PutBucketOwnershipControls`, same `BucketOwnerEnforced`. |
| frontend | ↳ Bucket (child) | `BucketEncryption` | — | `aws_s3_bucket_server_side_encryption_configuration` | `successfulsuccess-frontend-980553487282` | **Create**: `PutBucketEncryption`, same AES256. |
| frontend | `BucketPolicy` (child) | `AWS::S3::BucketPolicy` | `successfulsuccess-frontend-980553487282` | `aws_s3_bucket_policy` | `successfulsuccess-frontend-980553487282` | **Create**: `PutBucketPolicy` replaces the whole policy with the same CloudFront-read statement; CloudFront keeps reading throughout. |
| frontend | `OriginAccessControl` | `AWS::CloudFront::OriginAccessControl` | `E3505ODECP7COE` | `aws_cloudfront_origin_access_control` | `E3505ODECP7COE` | **Import**: the distribution's origin references this id; the name must be unique, so a create fails. |
| frontend | `IndexRewriteFunction` | `AWS::CloudFront::Function` | `arn:aws:cloudfront::980553487282:function/successfulsuccess-index-rewrite` | `aws_cloudfront_function` | `successfulsuccess-index-rewrite` | **Import**: name is unique; associated with the distribution. |
| frontend | `WebAcl` | `AWS::WAFv2::WebACL` | `successfulsuccess-frontend\|2409e371-13b3-4dae-ac6f-2fab34472d93\|CLOUDFRONT` | `aws_wafv2_web_acl` | `2409e371-13b3-4dae-ac6f-2fab34472d93/successfulsuccess-frontend/CLOUDFRONT` | **Import**: attached to the distribution. Order differs from CFN: Terraform wants `id/name/scope`. Needs a `us-east-1` provider (it is already). |
| frontend | `Distribution` | `AWS::CloudFront::Distribution` | `E3GWDPGGUUDNG6` | `aws_cloudfront_distribution` | `E3GWDPGGUUDNG6` | **Import**: a new distribution gets a new `*.cloudfront.net` name, which is the site URL, the Cognito callback and the CORS origin. |

### successfulsuccess-reports (15 → 26)

Not deployed: `RecipientIdentity` (`ReportRecipient` equals `SenderEmail`, so `HasSeparateRecipient` is false).

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| reports | `SenderIdentity` | `AWS::SES::EmailIdentity` | `<REPORT_SENDER>` | `aws_sesv2_email_identity` | `<REPORT_SENDER>` | **Import**: verified identity; a create fails (exists), and a re-created one is Pending until the link is clicked again. |
| reports | `ReportsBucket` | `AWS::S3::Bucket` | `successfulsuccess-reports-980553487282` | `aws_s3_bucket` | `successfulsuccess-reports-980553487282` | **Import**: global name; holds the reports. |
| reports | ↳ ReportsBucket (child) | `PublicAccessBlockConfiguration` | — | `aws_s3_bucket_public_access_block` | `successfulsuccess-reports-980553487282` | **Create**: PUT, same values. |
| reports | ↳ ReportsBucket (child) | `OwnershipControls` | — | `aws_s3_bucket_ownership_controls` | `successfulsuccess-reports-980553487282` | **Create**: PUT, same value. |
| reports | ↳ ReportsBucket (child) | `BucketEncryption` | — | `aws_s3_bucket_server_side_encryption_configuration` | `successfulsuccess-reports-980553487282` | **Create**: PUT, same AES256. |
| reports | ↳ ReportsBucket (child) | `LifecycleConfiguration` | — | `aws_s3_bucket_lifecycle_configuration` | `successfulsuccess-reports-980553487282` | **Create**: PUT replaces the whole lifecycle; same `expire-reports` rule (90 days, `reports/`). |
| reports | ↳ ReportsBucket (child) | `NotificationConfiguration` | — | `aws_s3_bucket_notification` | `successfulsuccess-reports-980553487282` | **Create**: `PutBucketNotificationConfiguration` replaces the bucket's one notification document with the same mailer trigger (`reports/` + `.csv`). It needs the mailer's invoke permission to exist first, which it does (imported). Add `depends_on` on the permission. |
| reports | `S3Endpoint` | `AWS::EC2::VPCEndpoint` | `vpce-022c326982c06adcd` | `aws_vpc_endpoint` | `vpce-022c326982c06adcd` | **Import**: a second S3 gateway endpoint on the same route table is refused (route to the prefix list already exists). Keep `route_table_ids = ["rtb-0fda711f924ebbb89"]` inline, with no `aws_vpc_endpoint_route_table_association`. |
| reports | `ReportRequestsDlq` | `AWS::SQS::Queue` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests-dlq` | `aws_sqs_queue` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests-dlq` | **Import**: may hold failed messages. Keep `redrive_allow_policy` as an inline attribute. |
| reports | `ReportRequests` | `AWS::SQS::Queue` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests` | `aws_sqs_queue` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests` | **Import**: the schedule targets its ARN; may hold messages. Keep `redrive_policy` inline. |
| reports | `BuilderRole` | `AWS::IAM::Role` | `successfulsuccess-reports-BuilderRole-JPft27avTz5X` | `aws_iam_role` | `successfulsuccess-reports-BuilderRole-JPft27avTz5X` | **Import**: keep the generated name. |
| reports | ↳ BuilderRole (child) | `Policies[write-reports]` | — | `aws_iam_role_policy` | `successfulsuccess-reports-BuilderRole-JPft27avTz5X:write-reports` | **Create**: `PutRolePolicy` with the same name overwrites it with the same document. |
| reports | ↳ BuilderRole (child) | `Policies[read-report-requests]` | — | `aws_iam_role_policy` | `successfulsuccess-reports-BuilderRole-JPft27avTz5X:read-report-requests` | **Create**: same reason. |
| reports | ↳ BuilderRole (child) | `ManagedPolicyArns` | — | `aws_iam_role_policy_attachment` | `successfulsuccess-reports-BuilderRole-JPft27avTz5X/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole` | **Create**: attaching an attached policy is a no-op. |
| reports | `BuilderLogGroup` | `AWS::Logs::LogGroup` | `/aws/lambda/successfulsuccess-report-builder` | `aws_cloudwatch_log_group` | `/aws/lambda/successfulsuccess-report-builder` | **Import**: a create fails (exists). |
| reports | `ReportBuilder` | `AWS::Lambda::Function` | `successfulsuccess-report-builder` | `aws_lambda_function` | `successfulsuccess-report-builder` | **Import**: env holds `DATABASE_URL` (sensitive state). |
| reports | `ReportRequestsMapping` (child) | `AWS::Lambda::EventSourceMapping` | `833c286c-dc9c-4723-b550-c58c4ed8604a` | `aws_lambda_event_source_mapping` | `833c286c-dc9c-4723-b550-c58c4ed8604a` | **Import**: a create adds a **second** poller on the same queue (the retained one keeps running), so reports could be built and emailed twice. |
| reports | `MailerRole` | `AWS::IAM::Role` | `successfulsuccess-reports-MailerRole-TWC33UJl9GHQ` | `aws_iam_role` | `successfulsuccess-reports-MailerRole-TWC33UJl9GHQ` | **Import**: keep the generated name. |
| reports | ↳ MailerRole (child) | `Policies[read-reports-send-email]` | — | `aws_iam_role_policy` | `successfulsuccess-reports-MailerRole-TWC33UJl9GHQ:read-reports-send-email` | **Create**: same-name PUT. |
| reports | ↳ MailerRole (child) | `ManagedPolicyArns` | — | `aws_iam_role_policy_attachment` | `successfulsuccess-reports-MailerRole-TWC33UJl9GHQ/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole` | **Create**: no-op attach. |
| reports | `MailerLogGroup` | `AWS::Logs::LogGroup` | `/aws/lambda/successfulsuccess-report-mailer` | `aws_cloudwatch_log_group` | `/aws/lambda/successfulsuccess-report-mailer` | **Import**: a create fails (exists). |
| reports | `ReportMailer` | `AWS::Lambda::Function` | `successfulsuccess-report-mailer` | `aws_lambda_function` | `successfulsuccess-report-mailer` | **Import**. Its code is inline (`ZipFile`) in the template: move it to a file and zip it with `archive_file`; the first plan shows a code update with the same content. |
| reports | `MailerInvokePermission` (child) | `AWS::Lambda::Permission` | `successfulsuccess-reports-MailerInvokePermission-m1O5VDaafbNI` | `aws_lambda_permission` | `successfulsuccess-report-mailer/successfulsuccess-reports-MailerInvokePermission-m1O5VDaafbNI` | **Import**: a create adds a duplicate S3 statement and leaves the retained one unmanaged. |
| reports | `SchedulerRole` | `AWS::IAM::Role` | `successfulsuccess-reports-SchedulerRole-owr1hcMdqr6O` | `aws_iam_role` | `successfulsuccess-reports-SchedulerRole-owr1hcMdqr6O` | **Import**: keep the generated name. |
| reports | ↳ SchedulerRole (child) | `Policies[send-report-requests]` | — | `aws_iam_role_policy` | `successfulsuccess-reports-SchedulerRole-owr1hcMdqr6O:send-report-requests` | **Create**: same-name PUT. |
| reports | `WeeklySchedule` | `AWS::Scheduler::Schedule` | `successfulsuccess-weekly-report` | `aws_scheduler_schedule` | `default/successfulsuccess-weekly-report` | **Import**: a create fails (name exists in group `default`); a second schedule would double the Monday report. |

### successfulsuccess-ai (6 → 9)

| Stack | LogicalId | CFN type | PhysicalId | Terraform resource type | Import ID | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| ai | `ParserRole` | `AWS::IAM::Role` | `successfulsuccess-ai-ParserRole-obsAxq4CzhVx` | `aws_iam_role` | `successfulsuccess-ai-ParserRole-obsAxq4CzhVx` | **Import**: keep the generated name. |
| ai | ↳ ParserRole (child) | `Policies[call-bedrock]` | — | `aws_iam_role_policy` | `successfulsuccess-ai-ParserRole-obsAxq4CzhVx:call-bedrock` | **Create**: same-name PUT. |
| ai | ↳ ParserRole (child) | `Policies[read-claude-api-key]` | — | `aws_iam_role_policy` | `successfulsuccess-ai-ParserRole-obsAxq4CzhVx:read-claude-api-key` | **Create**: same-name PUT (still exactly one SSM parameter). |
| ai | ↳ ParserRole (child) | `ManagedPolicyArns` | — | `aws_iam_role_policy_attachment` | `successfulsuccess-ai-ParserRole-obsAxq4CzhVx/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole` | **Create**: no-op attach. |
| ai | `ParserLogGroup` | `AWS::Logs::LogGroup` | `/aws/lambda/successfulsuccess-agenda-parser` | `aws_cloudwatch_log_group` | `/aws/lambda/successfulsuccess-agenda-parser` | **Import**: a create fails (exists). |
| ai | `ParserFunction` | `AWS::Lambda::Function` | `successfulsuccess-agenda-parser` | `aws_lambda_function` | `successfulsuccess-agenda-parser` | **Import**. |
| ai | `ParserUrl` | `AWS::Lambda::Url` | `arn:aws:lambda:us-east-1:980553487282:function:successfulsuccess-agenda-parser` | `aws_lambda_function_url` | `successfulsuccess-agenda-parser` | **Import**: a new URL gets a new host, baked into the frontend build as `NEXT_PUBLIC_PARSER_URL`. |
| ai | `ParserUrlPermission` (child) | `AWS::Lambda::Permission` | `successfulsuccess-ai-ParserUrlPermission-0z09tJvHuEQr` | `aws_lambda_permission` | `successfulsuccess-agenda-parser/successfulsuccess-ai-ParserUrlPermission-0z09tJvHuEQr` | **Import**: avoid a duplicate public statement. |
| ai | `ParserUrlInvokePermission` (child) | `AWS::Lambda::Permission` | `successfulsuccess-ai-ParserUrlInvokePermission-eQW0bbRW3bVL` | `aws_lambda_permission` | `successfulsuccess-agenda-parser/successfulsuccess-ai-ParserUrlInvokePermission-eQW0bbRW3bVL` | **Import**: same reason. |

### Not in any stack (read with data sources, never managed)

- Default VPC `vpc-004bed0269ebdd3c1` and its six default subnets: read from the API function's
  `vpc_config` (`data "aws_lambda_function" "api"`), as `make aws-deploy-reports` did. The main
  route table `rtb-0fda711f924ebbb89` is the default of variable `route_table_ids` (pinned, not
  looked up, so a new route table in the VPC never changes the endpoint).
- SSM SecureString `/successfulsuccess/anthropic-api-key` (made by hand; only its name is passed).
- Budget `monthly-5usd` (made by hand).
- ECR images: pushed by `make aws-push`, not infrastructure.

### Notes that affect the first `terraform plan`

- CloudFormation adds `aws:cloudformation:*` tags to resources. Users cannot change `aws:` tags and
  the provider ignores them, so they show no diff. Put `PROJECT_NAME` in the provider's
  `default_tags` instead of on every resource.
- Terraform state will contain `DbPassword`, the full `DATABASE_URL` (two function envs), and the
  Google `client_secret` (read back by the identity provider import). Use an encrypted remote
  backend (e.g. an S3 bucket with encryption and locking); never commit `terraform.tfstate`.
- Keep every IAM role name, the DB subnet group name and the queue/function/log group names as they
  are now. For these resources a changed name means a replacement.

## Stack outputs and where they are used

`.github/workflows/style.yml` only runs ruff and ESLint. It has no AWS step and reads **no**
output. No file other than the `Makefile` reads stack outputs (`CLAUDE.md` and `README.md`
only mention some). "Frontend build" means the `--build-arg`s of `make aws-deploy-frontend`
(`frontend/Dockerfile` `ARG NEXT_PUBLIC_*`).

| Stack | Output | Current value | Used by |
| --- | --- | --- | --- |
| ecr | `RepositoryUri` | `980553487282.dkr.ecr.us-east-1.amazonaws.com/successfulsuccess-backend` | Makefile: `aws-push` (tag/push, login host), `aws-deploy-backend`, `aws-deploy-reports`, `aws-deploy-ai` (resolve digest → `ImageUri`) |
| auth | `UserPoolId` | `us-east-1_xgnKmaDDO` | Makefile: `aws-deploy-backend` and `aws-deploy-ai` (`CognitoUserPoolId`), `aws-auth-env` (→ `COGNITO_USER_POOL_ID` in `.env`); frontend build `NEXT_PUBLIC_COGNITO_USER_POOL_ID` |
| auth | `UserPoolClientId` | `7kbe5h0m3qbr70us2niiumqc15` | Makefile: `aws-deploy-backend` and `aws-deploy-ai` (`CognitoClientId`), `aws-auth-env` (→ `COGNITO_CLIENT_ID`); frontend build `NEXT_PUBLIC_COGNITO_CLIENT_ID` |
| auth | `Issuer` | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xgnKmaDDO` | Makefile: `aws-deploy-backend` downloads `<Issuer>/.well-known/jwks.json` → `CognitoJwks` |
| auth | `Authority` | same as `Issuer` | Nothing automated; README (manual check of `/.well-known/openid-configuration`) |
| auth | `CognitoDomain` | `https://kvasovets.auth.us-east-1.amazoncognito.com` | Nothing |
| auth | `HostedDomain` | `kvasovets.auth.us-east-1.amazoncognito.com` | Makefile: `aws-auth-env` (→ `COGNITO_DOMAIN`); frontend build `NEXT_PUBLIC_COGNITO_DOMAIN` |
| auth | `GoogleRedirectUri` | `https://kvasovets.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` | Makefile: `aws-deploy-auth` prints it for the Google Cloud console (manual) |
| auth | `GoogleEnabled` | `true` | Makefile: `aws-auth-env` (→ `COGNITO_GOOGLE_ENABLED`); frontend build `NEXT_PUBLIC_COGNITO_GOOGLE_ENABLED` |
| backend | `ApiUrl` | `https://jqgnqbnsxr45eqffmlwpth5b5m0jmgyh.lambda-url.us-east-1.on.aws` | Makefile: `aws-url`, `aws-deploy-frontend` (guard + build); frontend build `NEXT_PUBLIC_API_BASE_URL` |
| backend | `HealthUrl` | `<ApiUrl>/health` | Only the `aws-status` table |
| backend | `DocsUrl` | `<ApiUrl>/docs` | Only the `aws-status` table |
| backend | `FunctionUrlDomain` | `jqgnqbnsxr45eqffmlwpth5b5m0jmgyh.lambda-url.us-east-1.on.aws` | Only the `aws-status` table |
| backend | `DatabaseEndpoint` | `successfulsuccess-db.cq5sm6qqgpxq.us-east-1.rds.amazonaws.com` | Only the `aws-status` table (`aws-deploy-reports` reads `DATABASE_URL` from the function config instead) |
| backend | `FunctionName` | `successfulsuccess-backend` | Makefile: `aws-migrate`, `aws-agendas`, `aws-status`, `aws-deploy-frontend` (CORS check). `aws-deploy-reports` and `aws-logs` hard-code the name instead |
| backend | `LogGroupName` | `/aws/lambda/successfulsuccess-backend` | Only the `aws-status` table (`aws-logs` hard-codes it) |
| frontend | `SiteUrl` | `https://d2yc332l6c63ao.cloudfront.net` | Makefile: `aws-frontend-url` |
| frontend | `DistributionDomain` | `d2yc332l6c63ao.cloudfront.net` | Makefile: `aws-deploy-auth` (Cognito callback/logout URLs), `aws-deploy-frontend` (CNAME hint for a custom domain) |
| frontend | `AllowedOrigins` | `https://d2yc332l6c63ao.cloudfront.net` | Makefile: `aws-deploy-backend` (`CorsOrigins`), `aws-deploy-ai` (`AllowedOrigins`, + localhost), `aws-deploy-frontend` (CORS drift check) |
| frontend | `BucketName` | `successfulsuccess-frontend-980553487282` | Makefile: `aws-deploy-frontend` (`s3 sync`), `aws-destroy` (empty bucket) |
| frontend | `DistributionId` | `E3GWDPGGUUDNG6` | Makefile: `aws-deploy-frontend` (`create-invalidation`) |
| frontend | `PricingPlanStatus` | `PAY_AS_YOU_GO` | Nothing automated; README |
| reports | `SenderIdentity` | `<REPORT_SENDER>` | Only the table `aws-deploy-reports` prints |
| reports | `RecipientIdentity` | `<REPORT_SENDER>` | Only that table |
| reports | `BucketName` | `successfulsuccess-reports-980553487282` | Makefile: `aws-destroy` (empty bucket) |
| reports | `BuilderFunctionName` | `successfulsuccess-report-builder` | Only that table |
| reports | `BuilderLogGroup` | `/aws/lambda/successfulsuccess-report-builder` | Only that table |
| reports | `QueueUrl` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests` | Makefile: `report-now` (`sqs send-message`), `dlq-status` |
| reports | `QueueArn` | `arn:aws:sqs:us-east-1:980553487282:successfulsuccess-report-requests` | Only that table |
| reports | `DlqUrl` | `https://sqs.us-east-1.amazonaws.com/980553487282/successfulsuccess-report-requests-dlq` | Makefile: `dlq-status` |
| reports | `MailerFunctionName` | `successfulsuccess-report-mailer` | Only that table |
| ai | `ParserUrl` | `https://otpam7bbdosyxlzsqc4wcydzly0ukhhz.lambda-url.us-east-1.on.aws` | Makefile: `aws-ai-url`, `aws-deploy-frontend`; frontend build `NEXT_PUBLIC_PARSER_URL` |
| ai | `FunctionName` | `successfulsuccess-agenda-parser` | Nothing (`aws-logs-ai` hard-codes the log group) |
| ai | `LogGroup` | `/aws/lambda/successfulsuccess-agenda-parser` | Nothing |

Every `$(call stack-output,...)` on the **auth**, **reports** and **ai** stacks above becomes
`terraform output -raw <name>` (`infra/outputs.tf`). Those used by the Makefile are `UserPoolId`,
`UserPoolClientId`, `Issuer`, `HostedDomain`, `GoogleEnabled`, `BucketName` (reports), `QueueUrl`,
`DlqUrl` and `ParserUrl`: the minimum Terraform has to provide for the Makefile to keep working.
Outputs of **ecr**, **backend** and **frontend** stay `stack-output` calls, since those stacks stay.

## Template parameters

**Secret** = must be a `sensitive` Terraform variable, never in a committed `.tfvars`.
**Personal** = not a secret, but stays in `.env`, not in code (owner's rule). Current values are
from `describe-stacks`. NoEcho values show as `****` there and are not reproduced.

| Stack | Parameter | Type | Current value (source) | Secret? |
| --- | --- | --- | --- | --- |
| all six | `ProjectName` | String | `successfulsuccess` | no |
| auth | `DomainPrefix` | String | `kvasovets` (`COGNITO_DOMAIN_PREFIX`) | no |
| auth | `CallbackUrls` | CommaDelimitedList | `https://d2yc332l6c63ao.cloudfront.net/auth/callback/,http://localhost:3000/auth/callback/` (derived) | no |
| auth | `LogoutUrls` | CommaDelimitedList | `https://d2yc332l6c63ao.cloudfront.net/,http://localhost:3000/` (derived) | no |
| auth | `GoogleClientId` | String | `<GOOGLE_CLIENT_ID>` (`.env`) | no (public OAuth id), personal |
| auth | `GoogleClientSecret` | String, **NoEcho** | `****` (`GOOGLE_CLIENT_SECRET`) | **SECRET** |
| backend | `VpcId` | VPC::Id | `vpc-004bed0269ebdd3c1` (looked up) | no |
| backend | `SubnetIds` | List<Subnet::Id> | the six default subnets (looked up) | no |
| backend | `ImageUri` | String | `<repo>@sha256:…` (resolved from `latest`) | no |
| backend | `Architecture` | String | `x86_64` (`AWS_LAMBDA_ARCH`) | no |
| backend | `MemorySize` | Number | `512` (default) | no |
| backend | `MaxConcurrency` | Number | `0` (default) | no |
| backend | `DbName` | String | `meetings` (default) | no |
| backend | `DbUsername` | String | `app` (default) | no |
| backend | `DbPassword` | String, **NoEcho** | `****` (`AWS_DB_PASSWORD`) | **SECRET** |
| backend | `AppTimezone` | String | `Europe/Kyiv` (`APP_TIMEZONE`) | no |
| backend | `CorsOrigins` | String | `https://d2yc332l6c63ao.cloudfront.net` (frontend output) | no |
| backend | `LogLevel` | String | `INFO` (default) | no |
| backend | `CognitoUserPoolId` | String | `us-east-1_xgnKmaDDO` (auth output) | no |
| backend | `CognitoClientId` | String | `7kbe5h0m3qbr70us2niiumqc15` (auth output) | no |
| backend | `CognitoJwks` | String | base64 of the pool's `jwks.json` (downloaded) | no (public keys) |
| frontend | `DomainName` | String | empty | no |
| frontend | `CertificateArn` | String | empty | no |
| frontend | `HostedZoneId` | String | empty | no |
| frontend | `PricingPlan` | String | `PAY_AS_YOU_GO` (`AWS_CLOUDFRONT_PLAN`) | no |
| reports | `SenderEmail` | String | `<REPORT_SENDER>` (`REPORT_SENDER`) | no, personal |
| reports | `ReportRecipient` | String | `<REPORT_SENDER>` (`REPORT_RECIPIENT`) | no, personal |
| reports | `VpcId` | VPC::Id | `vpc-004bed0269ebdd3c1` (from the API function) | no |
| reports | `SubnetIds` | List<Subnet::Id> | the same six subnets (from the API function) | no |
| reports | `RouteTableIds` | CommaDelimitedList | `rtb-0fda711f924ebbb89` (looked up) | no |
| reports | `SecurityGroupId` | SecurityGroup::Id | `sg-06b7e429066e1c5f3` (from the API function) | no |
| reports | `ImageUri` | String | `<repo>@sha256:…` | no |
| reports | `DatabaseUrl` | String, **NoEcho** | `****` (read from the API function's env; contains the DB password) | **SECRET** |
| reports | `ScheduleExpression` | String | `cron(0 7 ? * MON *)` (`SCHEDULE`) | no |
| reports | `FailWeek` | String | empty (`FAIL_WEEK`) | no |
| ai | `ImageUri` | String | `<repo>@sha256:…` | no |
| ai | `Architecture` | String | `x86_64` | no |
| ai | `ParserProvider` | String | `anthropic_api` (`PARSER_PROVIDER`) | no |
| ai | `ParserModel` | String | `claude-opus-5-5` (`PARSER_MODEL`) | no |
| ai | `AnthropicApiKeyParameter` | String | `/successfulsuccess/anthropic-api-key` | no: the parameter's **name**. The key itself (SSM SecureString) is secret and stays out of Terraform |
| ai | `CognitoUserPoolId` | String | `us-east-1_xgnKmaDDO` (auth output) | no |
| ai | `CognitoClientId` | String | `7kbe5h0m3qbr70us2niiumqc15` (auth output) | no |
| ai | `AllowedOrigins` | CommaDelimitedList | `https://d2yc332l6c63ao.cloudfront.net,http://localhost:3000` (derived) | no |
| ai | `LogLevel` | String | `INFO` (default) | no |

Three secrets: `GoogleClientSecret`, `DbPassword`, `DatabaseUrl`. In Terraform, `DatabaseUrl` no
longer needs to be a variable at all: build it from `DbPassword` and the `aws_db_instance` endpoint,
as `backend.yml` already does for the API.

## Resource count per stack

Moving to Terraform (the scope):

| Stack | CFN resources | Terraform resources | Import | Create (children) |
| --- | --- | --- | --- | --- |
| `successfulsuccess-auth` | 5 | 5 | 5 | 0 |
| `successfulsuccess-reports` | 15 | 26 | 15 | 11 |
| `successfulsuccess-ai` | 6 | 9 | 6 | 3 |
| **Total in scope** | **26** | **40** | **26** | **14** |

26 + 14 = 40. Not counted: `aws_sesv2_email_identity.recipient` (`count = 0`, as
`RecipientIdentity` was never deployed). There are no other Terraform resources.

Staying in CloudFormation (reference only, not imported, not created):

| Stack | CFN resources | Would be Terraform resources | Would be Import | Would be Create |
| --- | --- | --- | --- | --- |
| `successfulsuccess-ecr` | 1 | 3 | 1 | 2 |
| `successfulsuccess-backend` | 10 | 14 | 13 | 1 |
| `successfulsuccess-frontend` | 6 | 9 | 5 | 4 |
| **Total out of scope** | **17** | **26** | **19** | **7** |

All six stacks together: 43 CFN resources = 26 in scope + 17 out of scope.

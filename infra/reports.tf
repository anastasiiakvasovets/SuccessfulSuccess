# Weekly meetings report (was infra/reports.yml): built from the database on a
# schedule or on demand, saved as a CSV on S3 and emailed through SES. The
# builder runs in the backend's VPC with no NAT and reaches S3 through a
# gateway endpoint. SES sandbox: sender and recipient are verified addresses.

locals {
  reports_bucket = "${var.project_name}-reports-${local.account_id}"
  queue_name     = "${var.project_name}-report-requests"

  # Names CloudFormation generated. Kept as they are so every import is in place.
  builder_role_name   = "${var.project_name}-reports-BuilderRole-JPft27avTz5X"
  mailer_role_name    = "${var.project_name}-reports-MailerRole-TWC33UJl9GHQ"
  scheduler_role_name = "${var.project_name}-reports-SchedulerRole-owr1hcMdqr6O"
  mailer_statement_id = "${var.project_name}-reports-MailerInvokePermission-m1O5VDaafbNI"

  # Same caveat as the API: the password is readable in the function configuration.
  database_url = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s",
    data.aws_cloudformation_stack.backend.parameters["DbUsername"],
    var.db_password,
    data.aws_cloudformation_stack.backend.outputs["DatabaseEndpoint"],
    data.aws_cloudformation_stack.backend.parameters["DbName"],
  )
}

# --- email ----------------------------------------------------------------------

# Creating an identity mails a verification link; it stays Pending until clicked.
resource "aws_sesv2_email_identity" "sender" {
  email_identity = var.sender_email
}

resource "aws_sesv2_email_identity" "recipient" {
  count = var.report_recipient != var.sender_email ? 1 : 0

  email_identity = var.report_recipient
}

# --- storage ----------------------------------------------------------------------

# Emptied by `make aws-destroy` before it goes.
resource "aws_s3_bucket" "reports" {
  bucket = local.reports_bucket
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket = aws_s3_bucket.reports.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-reports"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    expiration {
      days = 90
    }
  }
}

# A new report is an event; the mailer reacts to it. S3 checks that it may
# invoke the mailer when this is set, hence depends_on the permission. Bucket,
# permission and notification are three resources, so there is no cycle.
resource "aws_s3_bucket_notification" "reports" {
  bucket = aws_s3_bucket.reports.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.mailer.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "reports/"
    filter_suffix       = ".csv"
  }

  depends_on = [aws_lambda_permission.mailer_s3]
}

# Free: a route to S3's prefix list in each route table.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_lambda_function.api.vpc_config[0].vpc_id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids

  tags = {
    Name = "${var.project_name}-s3"
  }
}

# --- queue ----------------------------------------------------------------------

# Messages the builder failed on three times wait here for 14 days.
resource "aws_sqs_queue" "report_requests_dlq" {
  name                      = "${local.queue_name}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  # SQS's default today (1 MiB); the provider's default is still 256 KiB.
  max_message_size = 1048576

  # Only the main queue may use this one as its DLQ. Its ARN is built from its
  # name: a reference would be circular (the main queue points here).
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = ["arn:${local.partition}:sqs:${local.region}:${local.account_id}:${local.queue_name}"]
  })
}

# One entry point for every report request: the schedule and `make report-now`.
resource "aws_sqs_queue" "report_requests" {
  name = local.queue_name
  # At least 6x the builder's timeout.
  visibility_timeout_seconds = 360
  sqs_managed_sse_enabled    = true
  # SQS's default today (1 MiB); the provider's default is still 256 KiB.
  max_message_size = 1048576

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.report_requests_dlq.arn
    maxReceiveCount     = 3
  })
}

# --- builder --------------------------------------------------------------------

resource "aws_iam_role" "builder" {
  name = local.builder_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Write logs, and manage the network interfaces a VPC function needs.
resource "aws_iam_role_policy_attachment" "builder_vpc_access" {
  role       = aws_iam_role.builder.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "builder_write_reports" {
  name = "write-reports"
  role = aws_iam_role.builder.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "arn:${local.partition}:s3:::${local.reports_bucket}/reports/*"
    }]
  })
}

# The Lambda service polls the queue with this role; the function itself never
# connects to SQS, which is why it needs no NAT or SQS endpoint.
resource "aws_iam_role_policy" "builder_read_report_requests" {
  name = "read-report-requests"
  role = aws_iam_role.builder.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = aws_sqs_queue.report_requests.arn
    }]
  })
}

resource "aws_cloudwatch_log_group" "builder" {
  name              = "/aws/lambda/${var.project_name}-report-builder"
  retention_in_days = 7
}

resource "aws_lambda_function" "builder" {
  function_name = "${var.project_name}-report-builder"
  description   = "Builds the weekly meetings report CSV and saves it to S3"
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = ["x86_64"]
  role          = aws_iam_role.builder.arn
  memory_size   = 512
  timeout       = 60

  image_config {
    command = ["app.reports.lambda_handler.handler"]
  }

  logging_config {
    log_group  = aws_cloudwatch_log_group.builder.name
    log_format = "JSON"
  }

  vpc_config {
    subnet_ids         = data.aws_lambda_function.api.vpc_config[0].subnet_ids
    security_group_ids = data.aws_lambda_function.api.vpc_config[0].security_group_ids
  }

  environment {
    variables = {
      DATABASE_URL   = local.database_url
      APP_TIMEZONE   = "Europe/Kyiv"
      LOG_LEVEL      = "INFO"
      REPORTS_BUCKET = aws_s3_bucket.reports.id
      FAIL_WEEK      = var.fail_week
    }
  }

  # `make aws-update-workers` deploys the image (aws-deploy-backend runs it too);
  # versions are never published.
  lifecycle {
    ignore_changes = [image_uri, publish]
  }

  # The endpoint must be routable before the first PutObject.
  depends_on = [aws_vpc_endpoint.s3]
}

# One message per invocation: a failure retries (and dead-letters) that one only.
resource "aws_lambda_event_source_mapping" "report_requests" {
  event_source_arn = aws_sqs_queue.report_requests.arn
  function_name    = aws_lambda_function.builder.arn
  batch_size       = 1
  enabled          = true
}

# --- mailer ---------------------------------------------------------------------

# Outside the VPC, so it reaches SES over the internet. It may read reports but
# never write them: it would trigger itself forever.
resource "aws_iam_role" "mailer" {
  name = local.mailer_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "mailer_basic_execution" {
  role       = aws_iam_role.mailer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "mailer_read_reports_send_email" {
  name = "read-reports-send-email"
  role = aws_iam_role.mailer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:${local.partition}:s3:::${local.reports_bucket}/reports/*"
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
        ]
        Resource = "arn:${local.partition}:ses:${local.region}:${local.account_id}:identity/*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "mailer" {
  name              = "/aws/lambda/${var.project_name}-report-mailer"
  retention_in_days = 7
}

# Only used when the function is created from scratch (filename and
# source_code_hash are ignored). A change to index.py goes out by hand:
# aws lambda update-function-code --zip-file with this archive.
data "archive_file" "mailer" {
  type        = "zip"
  source_file = "${path.module}/lambda/report_mailer/index.py"
  output_path = "${path.module}/.terraform/archives/report-mailer.zip"
}

resource "aws_lambda_function" "mailer" {
  function_name    = "${var.project_name}-report-mailer"
  description      = "Emails each new weekly report CSV through SES"
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.mailer.output_path
  source_code_hash = data.archive_file.mailer.output_base64sha256
  architectures    = ["x86_64"]
  role             = aws_iam_role.mailer.arn
  memory_size      = 256
  timeout          = 30

  logging_config {
    log_group  = aws_cloudwatch_log_group.mailer.name
    log_format = "JSON"
  }

  environment {
    variables = {
      SENDER = var.sender_email
      # Comma-separated; in the SES sandbox every address must be verified.
      RECIPIENTS = var.report_recipient
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash, publish]
  }
}

# Lets S3 invoke the mailer, for this bucket in this account only.
resource "aws_lambda_permission" "mailer_s3" {
  statement_id   = local.mailer_statement_id
  function_name  = aws_lambda_function.mailer.function_name
  action         = "lambda:InvokeFunction"
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.reports.arn
  source_account = local.account_id
}

# --- schedule -------------------------------------------------------------------

resource "aws_iam_role" "scheduler" {
  name = local.scheduler_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_send_report_requests" {
  name = "send-report-requests"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.report_requests.arn
    }]
  })
}

resource "aws_scheduler_schedule" "weekly_report" {
  name        = "${var.project_name}-weekly-report"
  group_name  = "default"
  description = "Build last week's meetings report every Monday morning"

  schedule_expression = var.schedule_expression
  # Without it the cron runs in UTC, and the report arrives at 9 or 10 Kyiv time.
  schedule_expression_timezone = "Europe/Kyiv"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # A command on the queue, not a direct invoke: retries and the DLQ come with
  # it. week null means "the week before", decided by the builder. The exact
  # string the schedule holds: jsonencode() would reorder and respace it.
  target {
    arn      = aws_sqs_queue.report_requests.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{\"week\": null, \"source\": \"schedule\"}"
  }
}

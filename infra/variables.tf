variable "project_name" {
  type        = string
  default     = "successfulsuccess"
  description = "Prefix for the names of the resources, and the PROJECT_NAME tag."
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "Region for everything. Never eu-central-1 (old stacks live there)."
}

variable "local_origin" {
  type        = string
  default     = "http://localhost:3000"
  description = "The dev server's origin, allowed next to the CloudFront site."
}

# --- auth ---------------------------------------------------------------------

variable "domain_prefix" {
  type        = string
  description = "Prefix of Cognito's OAuth domain, https://<prefix>.auth.<region>.amazoncognito.com (COGNITO_DOMAIN_PREFIX)."
}

variable "google_client_id" {
  type        = string
  default     = ""
  description = "OAuth client id of the Google \"Web application\" client. Empty leaves Google sign-in out."
}

variable "google_client_secret" {
  type        = string
  sensitive   = true
  description = "That Google client's secret (GOOGLE_CLIENT_SECRET). Pass \"\" when google_client_id is empty."
}

# --- reports ------------------------------------------------------------------

variable "sender_email" {
  type        = string
  description = "The address reports are sent from (REPORT_SENDER in .env). Never in terraform.tfvars."

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.sender_email))
    error_message = "sender_email must be an email address."
  }
}

variable "report_recipient" {
  type        = string
  description = "Where reports go (REPORT_RECIPIENT in .env). Never in terraform.tfvars. When it equals sender_email, one identity covers both."

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.report_recipient))
    error_message = "report_recipient must be an email address."
  }
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "The RDS master password (AWS_DB_PASSWORD), for the builder's DATABASE_URL."
}

variable "route_table_ids" {
  type        = list(string)
  default     = ["rtb-0fda711f924ebbb89"]
  description = "Route tables that get the S3 gateway endpoint: the backend VPC's main route table, which all six default subnets use."
}

variable "schedule_expression" {
  type        = string
  default     = "cron(0 7 ? * MON *)"
  description = "When the weekly report is built, in Europe/Kyiv time. rate(5 minutes) for testing."
}

variable "fail_week" {
  type        = string
  default     = ""
  description = "Testing only: the builder raises for this ISO week, so its message lands in the DLQ."

  validation {
    condition     = can(regex("^$|^\\d{4}-W\\d{2}$", var.fail_week))
    error_message = "fail_week must be empty or an ISO week like 2026-W01."
  }
}

# --- ai -----------------------------------------------------------------------

variable "image_uri" {
  type        = string
  default     = ""
  description = "Backend image for a function created from scratch. Empty: <RepositoryUri>:latest. Ignored afterwards (make aws-update-workers deploys code)."
}

variable "architecture" {
  type        = string
  default     = "x86_64"
  description = "The agenda parser's architecture; must match the image's platform."

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be x86_64 or arm64."
  }
}

variable "parser_provider" {
  type        = string
  default     = "anthropic"
  description = "anthropic (Messages API on Bedrock), converse (Bedrock Converse), anthropic_api (the Claude API) or fake."

  validation {
    condition     = contains(["anthropic", "converse", "anthropic_api", "fake"], var.parser_provider)
    error_message = "parser_provider must be anthropic, converse, anthropic_api or fake."
  }
}

variable "parser_model" {
  type        = string
  default     = "anthropic.claude-opus-5-5"
  description = "The model id for that provider."
}

variable "anthropic_api_key_parameter" {
  type        = string
  default     = "/successfulsuccess/anthropic-api-key"
  description = "Name of the SSM SecureString holding the Claude API key (made by hand; only its name is here)."

  validation {
    condition     = can(regex("^/[A-Za-z0-9_./-]+$", var.anthropic_api_key_parameter))
    error_message = "anthropic_api_key_parameter must be an SSM parameter name starting with /."
  }
}

variable "log_level" {
  type        = string
  default     = "INFO"
  description = "The agenda parser's log level."

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be DEBUG, INFO, WARNING or ERROR."
  }
}

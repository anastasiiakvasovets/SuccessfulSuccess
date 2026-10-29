# Non-secret values for the successfulsuccess-dev workspace (current CloudFormation
# parameters). Secrets and email addresses are NOT here: set google_client_secret,
# db_password, sender_email and report_recipient as $env:TF_VAR_<name> when the
# workspace runs in Local execution mode (the import), or as HCP Terraform
# workspace variables for remote runs (secrets marked Sensitive).

project_name = "successfulsuccess"
aws_region   = "us-east-1"
local_origin = "http://localhost:3000"

# auth
domain_prefix    = "kvasovets"
google_client_id = "225506027640-780d83o8lu8dd1ilqhuei9b76aged1ai.apps.googleusercontent.com"

# reports
route_table_ids     = ["rtb-0fda711f924ebbb89"]
schedule_expression = "cron(0 7 ? * MON *)"
fail_week           = ""

# ai
architecture                = "x86_64"
parser_provider             = "anthropic_api"
parser_model                = "claude-opus-5-5"
anthropic_api_key_parameter = "/successfulsuccess/anthropic-api-key"
log_level                   = "INFO"

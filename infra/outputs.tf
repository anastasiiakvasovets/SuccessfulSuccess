# The outputs of auth.yml, reports.yml and ai.yml, under snake_case names.
# `$(call stack-output,<stack>,UserPoolId)` becomes `terraform output -raw user_pool_id`.

# --- auth -----------------------------------------------------------------------

output "user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "issuer" {
  description = "The \"iss\" of every token; its signing keys are at <issuer>/.well-known/jwks.json"
  value       = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
}

output "authority" {
  description = "OIDC authority; <authority>/.well-known/openid-configuration describes it"
  value       = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
}

output "cognito_domain" {
  description = "Cognito's OAuth domain as a URL (managed login, /logout)"
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${local.region}.amazoncognito.com"
}

output "hosted_domain" {
  description = "Cognito's OAuth domain, which the frontend sends Google sign-in through"
  value       = "${aws_cognito_user_pool_domain.this.domain}.auth.${local.region}.amazoncognito.com"
}

output "google_redirect_uri" {
  description = "Add this to the Google client's \"Authorized redirect URIs\""
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${local.region}.amazoncognito.com/oauth2/idpresponse"
}

output "google_enabled" {
  value = local.google_enabled ? "true" : "false"
}

# --- reports --------------------------------------------------------------------

output "sender_identity" {
  value = aws_sesv2_email_identity.sender.email_identity
}

output "recipient_identity" {
  value = one(concat(aws_sesv2_email_identity.recipient[*].email_identity, [aws_sesv2_email_identity.sender.email_identity]))
}

output "reports_bucket_name" {
  value = aws_s3_bucket.reports.id
}

output "builder_function_name" {
  value = aws_lambda_function.builder.function_name
}

output "builder_log_group" {
  value = aws_cloudwatch_log_group.builder.name
}

output "queue_url" {
  description = "Where `make report-now` sends report requests"
  value       = aws_sqs_queue.report_requests.url
}

output "queue_arn" {
  value = aws_sqs_queue.report_requests.arn
}

output "dlq_url" {
  value = aws_sqs_queue.report_requests_dlq.url
}

output "mailer_function_name" {
  value = aws_lambda_function.mailer.function_name
}

# --- ai -------------------------------------------------------------------------

output "parser_url" {
  description = "Where the browser POSTs pasted text (the function URL, without its trailing slash)"
  value       = trimsuffix(aws_lambda_function_url.parser.function_url, "/")
}

output "parser_function_name" {
  value = aws_lambda_function.parser.function_name
}

output "parser_log_group" {
  value = aws_cloudwatch_log_group.parser.name
}

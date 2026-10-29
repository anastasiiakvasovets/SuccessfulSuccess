# Sign-in (was infra/auth.yml): a Cognito user pool where people sign up with
# their email and a password, optionally federated with Google, plus the public
# app client the Next.js frontend signs in through.

locals {
  google_enabled = var.google_client_id != ""
}

resource "aws_cognito_user_pool" "users" {
  name = "${var.project_name}-users"

  # People sign in with their email address; Cognito mails them a code to
  # confirm it on sign-up and to reset a forgotten password.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  username_configuration {
    case_sensitive = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # The constraints are what Cognito stores for the standard email attribute;
  # leaving them out shows a diff on every plan.
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  # Cognito's own mailer: free, but capped at 50 emails a day.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Essentials is what managed login (version 2) needs.
  user_pool_tier = "ESSENTIALS"
}

# https://<prefix>.auth.<region>.amazoncognito.com
resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.users.id
  # 2 = managed login (the newer hosted pages), styled by the branding below.
  managed_login_version = 2
}

resource "aws_cognito_managed_login_branding" "web" {
  user_pool_id                = aws_cognito_user_pool.users.id
  client_id                   = aws_cognito_user_pool_client.web.id
  use_cognito_provided_values = true

  depends_on = [aws_cognito_user_pool_domain.this]
}

resource "aws_cognito_identity_provider" "google" {
  count = local.google_enabled ? 1 : 0

  user_pool_id  = aws_cognito_user_pool.users.id
  provider_name = "Google"
  provider_type = "Google"

  # The keys after client_secret are the ones Cognito fills in for Google;
  # listing them keeps the plan clean.
  provider_details = {
    client_id                     = var.google_client_id
    client_secret                 = var.google_client_secret
    authorize_scopes              = "openid email profile"
    attributes_url                = "https://people.googleapis.com/v1/people/me?personFields="
    attributes_url_add_attributes = "true"
    authorize_url                 = "https://accounts.google.com/o/oauth2/v2/auth"
    oidc_issuer                   = "https://accounts.google.com"
    token_request_method          = "POST"
    token_url                     = "https://www.googleapis.com/oauth2/v4/token"
  }

  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
    username       = "sub"
  }
}

# Public client for the browser: no secret, SRP for passwords, and the
# authorization-code flow with PKCE for Google.
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project_name}-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret = false
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Referencing the provider also makes the client wait for it.
  supported_identity_providers = concat(
    ["COGNITO"],
    aws_cognito_identity_provider.google[*].provider_name,
  )

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  # Exact match, trailing slash included.
  callback_urls = [for origin in local.site_origins : "${origin}/auth/callback/"]
  logout_urls   = [for origin in local.site_origins : "${origin}/"]
}

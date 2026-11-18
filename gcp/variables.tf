variable "project_id" {
  description = "Google Cloud project that holds Spry's core."
  type        = string
  default     = "spry-kvasovets-2026"
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "api_image" {
  description = "API image (backend/Dockerfile), ideally pinned by digest. The default is Google's sample, so the first apply works before anything is pushed."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

# Sign-in stays on AWS (ADR 0008): Cloud Run verifies Cognito access tokens
# against the pool's public JWKS. These ids are not secrets.
variable "cognito_region" {
  description = "Region of the Cognito user pool."
  type        = string
}

variable "cognito_user_pool_id" {
  description = "Cognito user pool id (us-east-1_...)."
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito app client id used by the frontend."
  type        = string
}

variable "cors_origins" {
  description = "CORS_ORIGINS for the API, comma-separated. Behind the Firebase /api/** rewrite the site and the API share an origin, so only the dev server is needed."
  type        = string
  default     = "http://localhost:3000"
}

variable "db_activation_policy" {
  description = "Cloud SQL activation policy: ALWAYS = running, NEVER = stopped (storage is still billed). ADR 0008, option B."
  type        = string
  default     = "ALWAYS"

  validation {
    condition     = contains(["ALWAYS", "NEVER"], var.db_activation_policy)
    error_message = "db_activation_policy must be ALWAYS or NEVER."
  }
}

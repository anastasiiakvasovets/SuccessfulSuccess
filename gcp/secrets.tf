# The database password: letters and digits only, so it goes into the URL
# without escaping. It is in the Terraform state (HCP Terraform, encrypted) and
# in Secret Manager, never in an output or an env var's plain value.
resource "random_password" "db" {
  length  = 32
  special = false
}

locals {
  # Cloud Run mounts the instance's Unix socket under /cloudsql; asyncpg takes
  # the socket directory from ?host=. backend/app/config.py reads it unchanged.
  database_url = "postgresql+asyncpg://app:${random_password.db.result}@/meetings?host=/cloudsql/${google_sql_database_instance.spry.connection_name}"
}

# The whole DATABASE_URL, read by the API service and the migration job.
resource "google_secret_manager_secret" "database_url" {
  secret_id = "spry-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

# The bare password, for people connecting through the Cloud SQL Auth Proxy
# (psql, seeding). Not readable by spry-api.
resource "google_secret_manager_secret" "db_password" {
  secret_id = "spry-db-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}

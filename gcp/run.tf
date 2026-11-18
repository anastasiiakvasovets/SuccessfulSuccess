# The API on Cloud Run: backend/Dockerfile (uvicorn on :8000). Replaces the
# Lambda + function URL of infra/backend.yml.

locals {
  sql_connection_name = google_sql_database_instance.spry.connection_name
}

resource "google_cloud_run_v2_service" "api" {
  name     = "spry-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  # Lab: allow terraform destroy.
  deletion_protection = false

  template {
    service_account = google_service_account.api.email

    # db-f1-micro allows ~25 connections, and one instance can open up to 15
    # (SQLAlchemy's default pool 5 + overflow 10), so at most 2 instances.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.sql_connection_name]
      }
    }

    containers {
      image = var.api_image

      # backend/Dockerfile listens on 8000. Cloud Run sets PORT=8000, which the
      # placeholder image honours too.
      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true # CPU only while a request is handled
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      # Migrations run in the spry-migrate job, never on instance start.
      env {
        name  = "RUN_MIGRATIONS_ON_START"
        value = "false"
      }
      env {
        name  = "APP_TIMEZONE"
        value = "Europe/Kyiv"
      }
      env {
        name  = "CORS_ORIGINS"
        value = var.cors_origins
      }
      # No COGNITO_JWKS: unlike the VPC Lambda, Cloud Run reaches the internet
      # and fetches the pool's jwks.json itself.
      env {
        name  = "COGNITO_REGION"
        value = var.cognito_region
      }
      env {
        name  = "COGNITO_USER_POOL_ID"
        value = var.cognito_user_pool_id
      }
      env {
        name  = "COGNITO_CLIENT_ID"
        value = var.cognito_client_id
      }
    }
  }

  # The first revision must be able to read the secret and reach the database.
  depends_on = [
    google_project_service.this,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_iam_member.api_database_url,
    google_project_iam_member.api_cloudsql_client,
  ]
}

# Public service: Firebase Hosting's /api/** rewrite requires one, as the
# Lambda function URL was public (AuthType: NONE). The API itself checks a
# Cognito access token on every /api/v1 request (401 without one).
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Database migrations: `alembic upgrade head` with the service's image, SA,
# socket and secret. The counterpart of `make aws-migrate`. Run with
# `gcloud run jobs execute spry-migrate --region us-central1 --wait`.
resource "google_cloud_run_v2_job" "migrate" {
  name     = "spry-migrate"
  location = var.region

  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account = google_service_account.api.email
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [local.sql_connection_name]
        }
      }

      containers {
        image = var.api_image
        # Replaces CMD only: entrypoint.sh stays, skips its own migration
        # (RUN_MIGRATIONS_ON_START=false) and execs alembic once.
        args = ["alembic", "upgrade", "head"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "RUN_MIGRATIONS_ON_START"
          value = "false"
        }
        env {
          name  = "APP_TIMEZONE"
          value = "Europe/Kyiv"
        }
      }
    }
  }

  depends_on = [
    google_project_service.this,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_iam_member.api_database_url,
    google_project_iam_member.api_cloudsql_client,
  ]
}

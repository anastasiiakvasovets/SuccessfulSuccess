# Cloud SQL for PostgreSQL 16 (ADR 0008, option B): the smallest shared-core
# tier, no HA, no backups (lab data, re-seeded with app.seed). Stop it with
# db_activation_policy = "NEVER" when nobody uses it; storage is billed anyway.
resource "google_sql_database_instance" "spry" {
  name             = "spry-db"
  database_version = "POSTGRES_16"
  region           = var.region

  # Lab: allow terraform destroy (both the Terraform-side and the API-side flag).
  deletion_protection = false

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = false
    activation_policy = var.db_activation_policy

    deletion_protection_enabled = false

    backup_configuration {
      enabled = false
    }

    # A public IP with no authorized networks: nothing can connect to it
    # directly. Cloud Run (the /cloudsql socket), the Cloud SQL connectors and
    # the Auth Proxy go through the Cloud SQL Admin API, authorised by IAM
    # (roles/cloudsql.client), with TLS. No VPC or private IP to manage.
    ip_configuration {
      ipv4_enabled = true
    }

    user_labels = local.labels
  }

  depends_on = [google_project_service.this]
}

resource "google_sql_database" "meetings" {
  name     = "meetings"
  instance = google_sql_database_instance.spry.name
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.spry.name
  password = random_password.db.result
}

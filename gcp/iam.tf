# Two service accounts (ADR 0008, Identity & access). No basic roles (Owner /
# Editor), no service-account keys, and the default compute SA is not used.

# --- spry-api@: the identity Cloud Run (service and migration job) runs as -----

resource "google_service_account" "api" {
  account_id   = "spry-api"
  display_name = "Spry API (Cloud Run)"
  description  = "Runs the spry-api service and the spry-migrate job."

  depends_on = [google_project_service.this]
}

# Connect to Cloud SQL through the /cloudsql socket (Cloud SQL Admin API).
resource "google_project_iam_member" "api_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.api.member
}

# Read DATABASE_URL: on that one secret, not project-wide.
resource "google_secret_manager_secret_iam_member" "api_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

# --- terraform@: changes this configuration's infrastructure ------------------
#
# Today the owner's ADC runs Terraform (Local execution) and creates this
# account too. It is the identity for remote runs through Workload Identity
# Federation (a later step) and for optional local impersonation. No key.

resource "google_service_account" "terraform" {
  account_id   = "terraform"
  display_name = "Terraform (spry-gcp)"
  description  = "Manages the gcp/ configuration. Keyless: WIF or impersonation only."

  depends_on = [google_project_service.this]
}

locals {
  terraform_roles = {
    # Cloud Run service and job, and their IAM (the allUsers invoker binding).
    "roles/run.admin" = ""
    # Cloud SQL instance, database and user.
    "roles/cloudsql.admin" = ""
    # The Artifact Registry repository.
    "roles/artifactregistry.admin" = ""
    # Secrets, their versions and the per-secret accessor binding.
    "roles/secretmanager.admin" = ""
    # google_project_service (enabling APIs).
    "roles/serviceusage.serviceUsageAdmin" = ""
    # Not in the original list: creating and updating the two service accounts.
    "roles/iam.serviceAccountAdmin" = ""
  }

  # Roles granted with google_project_iam_member in this file. The project IAM
  # admin role below may grant or revoke only these.
  grantable_roles = concat(["roles/cloudsql.client"], keys(local.terraform_roles))
}

resource "google_project_iam_member" "terraform" {
  for_each = local.terraform_roles

  project = var.project_id
  role    = each.key
  member  = google_service_account.terraform.member
}

# Not in the original list: the project-level bindings above
# (google_project_iam_member) need setIamPolicy on the project. That role could
# grant anything, Owner included, so a condition limits it to the roles this
# configuration grants.
resource "google_project_iam_member" "terraform_project_iam_admin" {
  project = var.project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = google_service_account.terraform.member

  condition {
    title       = "only-spry-roles"
    description = "May grant or revoke only the roles managed in gcp/iam.tf."
    expression  = "api.getAttribute('iam.googleapis.com/modifiedGrantsByRole', []).hasOnly(${jsonencode(local.grantable_roles)})"
  }
}

# Deploying Cloud Run as spry-api requires actAs on that account. Granted on
# spry-api only, not project-wide, so terraform@ cannot act as any other SA.
resource "google_service_account_iam_member" "terraform_acts_as_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.terraform.member
}

# Not granted: Firebase Hosting admin (no Hosting resources here yet; add it
# with them), Workload Identity Pool admin (comes with the WIF step).

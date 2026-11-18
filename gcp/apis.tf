# APIs the core needs. Kept enabled on destroy: turning an API off can break
# resources managed elsewhere, and enabling is free.
locals {
  services = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "logging.googleapis.com",
  ])
}

resource "google_project_service" "this" {
  for_each = local.services

  service            = each.value
  disable_on_destroy = false
}

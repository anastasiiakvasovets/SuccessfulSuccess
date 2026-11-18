# The API image (backend/Dockerfile, linux/amd64), deployed by digest as on AWS.
resource "google_artifact_registry_repository" "spry" {
  location      = var.region
  repository_id = "spry"
  format        = "DOCKER"
  description   = "Spry API images"

  depends_on = [google_project_service.this]
}

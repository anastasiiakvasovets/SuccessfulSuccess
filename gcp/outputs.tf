# No secrets here: the password and DATABASE_URL stay in Secret Manager.

output "cloud_run_url" {
  description = "URL of the spry-api service (*.run.app)."
  value       = google_cloud_run_v2_service.api.uri
}

output "sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance), for the Auth Proxy."
  value       = google_sql_database_instance.spry.connection_name
}

output "sql_instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.spry.name
}

output "artifact_registry_repo_url" {
  description = "Docker repository for the API image."
  value       = "${google_artifact_registry_repository.spry.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.spry.repository_id}"
}

output "api_sa_email" {
  description = "Service account the service and the migration job run as."
  value       = google_service_account.api.email
}

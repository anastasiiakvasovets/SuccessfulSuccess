# Lab 9 (ADR 0008): Spry's core on Google Cloud. A root module of its own,
# separate from infra/ (AWS): its own HCP Terraform workspace and state, and no
# references to infra/. The workspace runs in Local execution mode with the
# owner's Application Default Credentials; Workload Identity Federation for
# remote runs is a later step. No make target applies.

terraform {
  required_version = ">= 1.10"

  cloud {
    organization = "ooad-nastyakvasovets"

    workspaces {
      name = "spry-gcp"
    }
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    # For the Firebase resources to come (Hosting site); nothing uses it yet.
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

locals {
  labels = {
    project    = "spry"
    managed-by = "terraform"
  }
}

provider "google" {
  project        = var.project_id
  region         = var.region
  default_labels = local.labels
}

provider "google-beta" {
  project        = var.project_id
  region         = var.region
  default_labels = local.labels
}

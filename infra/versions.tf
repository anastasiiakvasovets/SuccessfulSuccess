# Lab 7: the auth, reports and ai stacks move from CloudFormation to Terraform.
# ecr, backend (API + database + network) and frontend (site) stay in
# CloudFormation and are read below with data "aws_cloudformation_stack".

terraform {
  required_version = ">= 1.10"

  cloud {
    organization = "ooad-nastyakvasovets"

    workspaces {
      name = "successfulsuccess-dev"
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # Zips the report mailer's code (it was inline ZipFile in infra/reports.yml).
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      PROJECT_NAME = var.project_name
      ManagedBy    = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

# --- stacks that stay in CloudFormation ---------------------------------------

data "aws_cloudformation_stack" "ecr" {
  name = "${var.project_name}-ecr"
}

data "aws_cloudformation_stack" "backend" {
  name = "${var.project_name}-backend"
}

data "aws_cloudformation_stack" "frontend" {
  name = "${var.project_name}-frontend"
}

# The report builder joins the API function's network and database, read from
# that function as `make aws-deploy-reports` did.
data "aws_lambda_function" "api" {
  function_name = data.aws_cloudformation_stack.backend.outputs["FunctionName"]
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  # Code is deployed by `make aws-update-workers`; this is only used if a function
  # is ever created from scratch (every aws_lambda_function ignores image_uri).
  image_uri = var.image_uri != "" ? var.image_uri : "${data.aws_cloudformation_stack.ecr.outputs["RepositoryUri"]}:latest"

  # Every origin the site is served from: the CloudFront site and the dev server.
  site_origin  = "https://${data.aws_cloudformation_stack.frontend.outputs["DistributionDomain"]}"
  site_origins = [local.site_origin, var.local_origin]
}

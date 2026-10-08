terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.68" }
  }
  backend "s3" {
    bucket       = "climaroute-tfstate-723949188124"
    key          = "climaroute/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "climaroute" }
  }
}

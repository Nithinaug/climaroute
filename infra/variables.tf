variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "image_tag" {
  description = "ECR image tag to deploy (printed by push_image.sh)"
  type        = string
  default     = ""
}

variable "allowed_origins" {
  description = "CORS origins for the API (Amplify URL + local dev)"
  type        = list(string)
  default     = ["http://localhost:5173"]
}

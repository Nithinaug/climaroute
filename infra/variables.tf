variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "image_tag" {
  description = "ECR image tag to deploy (printed by push_image.sh, or the current one from: aws lambda get-function --function-name climaroute-api --query Code.ImageUri)"
  type        = string
}

variable "allowed_origins" {
  description = "CORS origins for the API (Amplify URL + local dev)"
  type        = list(string)
  default     = ["https://main.d1lxnvpn0ohz9a.amplifyapp.com", "http://localhost:5173"]
}

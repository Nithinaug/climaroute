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

variable "area_name" {
  description = "Covered area shown in the app; must match the data built by prepare"
  type        = string
  default     = "Koramangala, Bengaluru"
}

variable "area_bbox" {
  description = "min_lon,min_lat,max_lon,max_lat of the covered area"
  type        = string
  default     = "77.612,12.925,77.636,12.945"
}

variable "osm_extract_url" {
  description = "Regional OSM extract the prepare task clips the area from"
  type        = string
  default     = "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"
}

variable "prepare_image_tag" {
  description = "ECR tag of the prepare image (pushed by infra/push_image.sh prepare)"
  type        = string
  default     = "prepare"
}

variable "prepare_cpu" {
  type    = number
  default = 4096
}

variable "prepare_memory" {
  description = "MB; 30720 is the Fargate maximum for 4 vCPU"
  type        = number
  default     = 30720
}

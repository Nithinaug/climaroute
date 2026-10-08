output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "pipeline_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

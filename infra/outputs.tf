output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "ecr_repository_url" {
  value = local.repo_url
}

output "reports_table" {
  value = aws_dynamodb_table.reports.name
}

output "pipeline_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "prepare_network" {
  description = "awsvpcConfiguration for aws ecs run-task (used by run_prepare.sh)"
  value       = "subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${data.aws_security_group.default.id}],assignPublicIp=ENABLED"
}

output "prepare_cluster" {
  value = aws_ecs_cluster.main.name
}

output "prepare_task_definition" {
  value = aws_ecs_task_definition.prepare.family
}

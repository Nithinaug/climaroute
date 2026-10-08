data "aws_caller_identity" "current" {}

locals {
  name      = "climaroute"
  account   = data.aws_caller_identity.current.account_id
  image_uri = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  sfn_name  = "${local.name}-shade-pipeline"
  sfn_arn   = "arn:aws:states:${var.region}:${local.account}:stateMachine:${local.sfn_name}"

  # name => handler, memory MB, timeout s
  functions = {
    api        = { handler = "api.main.handler", memory = 2048, timeout = 29 }
    shade-tile = { handler = "pipeline.handlers.shade_tile", memory = 1024, timeout = 240 }
    merge      = { handler = "pipeline.handlers.merge", memory = 2048, timeout = 600 }
  }
}

# ---------- Storage ----------

resource "aws_s3_bucket" "data" {
  bucket = "${local.name}-data-${local.account}"
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_ecr_repository" "app" {
  name         = local.name
  force_delete = true
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# ---------- Lambdas ----------

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_data" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.data.arn}/*" },
      # ListBucket makes a missing key return NoSuchKey instead of AccessDenied.
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.data.arn },
    ]
  })
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "fn" {
  for_each      = local.functions
  function_name = "${local.name}-${each.key}"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = ["x86_64"]
  memory_size   = each.value.memory
  timeout       = each.value.timeout

  image_config {
    command = [each.value.handler]
  }

  environment {
    variables = {
      DATA_BUCKET     = aws_s3_bucket.data.bucket
      ALLOWED_ORIGINS = join(",", var.allowed_origins)
      LOG_LEVEL       = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.fn]
}

# ---------- HTTP API ----------

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
  # CORS is handled by FastAPI (one place for local and deployed).
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn["api"].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_rate_limit  = 20
    throttling_burst_limit = 40
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------- Keep-warm ping ----------

resource "aws_cloudwatch_event_rule" "warmup" {
  name                = "${local.name}-warmup"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "warmup" {
  rule  = aws_cloudwatch_event_rule.warmup.name
  arn   = aws_lambda_function.fn["api"].arn
  input = jsonencode({ warmup = true })
}

resource "aws_lambda_permission" "warmup" {
  statement_id  = "AllowWarmup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.warmup.arn
}

# ---------- Shade pipeline (Step Functions) ----------

resource "aws_iam_role" "sfn" {
  name = "${local.name}-sfn"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = flatten([for k in ["shade-tile", "merge"] : [
          aws_lambda_function.fn[k].arn, "${aws_lambda_function.fn[k].arn}:*"
        ]])
      },
      { Effect = "Allow", Action = "s3:GetObject", Resource = "${aws_s3_bucket.data.arn}/tiles/index.json" },
      # Distributed Map runs each batch as a child execution of this state machine.
      { Effect = "Allow", Action = "states:StartExecution", Resource = local.sfn_arn },
      {
        Effect   = "Allow"
        Action   = ["states:DescribeExecution", "states:StopExecution"]
        Resource = "arn:aws:states:${var.region}:${local.account}:execution:${local.sfn_name}/*"
      },
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = local.sfn_name
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/pipeline.asl.json", {
    bucket   = aws_s3_bucket.data.bucket
    shade_fn = aws_lambda_function.fn["shade-tile"].arn
    merge_fn = aws_lambda_function.fn["merge"].arn
  })
}

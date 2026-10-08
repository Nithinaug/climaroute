# Builds an area's data (prepare/). Started by run_prepare.sh, not on a schedule.

data "aws_vpc" "default" { default = true }

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_security_group" "default" {
  vpc_id = data.aws_vpc.default.id
  name   = "default"
}

resource "aws_ecs_cluster" "main" {
  name = local.name
}

resource "aws_cloudwatch_log_group" "prepare" {
  name              = "/ecs/${local.name}-prepare"
  retention_in_days = 14
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "prepare_exec" {
  name               = "${local.name}-prepare-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "prepare_exec" {
  role       = aws_iam_role.prepare_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "prepare_task" {
  name               = "${local.name}-prepare-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "prepare_task" {
  role = aws_iam_role.prepare_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.data.arn}/*" },
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.data.arn },
    ]
  })
}

resource "aws_ecs_task_definition" "prepare" {
  family                   = "${local.name}-prepare"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.prepare_cpu
  memory                   = var.prepare_memory
  execution_role_arn       = aws_iam_role.prepare_exec.arn
  task_role_arn            = aws_iam_role.prepare_task.arn
  ephemeral_storage { size_in_gib = 50 }

  container_definitions = jsonencode([{
    name      = "prepare"
    image     = "${aws_ecr_repository.app.repository_url}:${var.prepare_image_tag}"
    essential = true
    environment = [for k, v in merge(local.area_env, {
      DATA_BUCKET     = aws_s3_bucket.data.bucket
      OSM_EXTRACT_URL = var.osm_extract_url
    }) : { name = k, value = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.prepare.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "prepare"
      }
    }
  }])
}

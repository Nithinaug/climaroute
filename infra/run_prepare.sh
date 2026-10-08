#!/usr/bin/env bash
# Runs the prepare task for the current workspace's city and waits. Logs: /ecs/<name>-prepare
set -euo pipefail
cd "$(dirname "$0")"
CLUSTER=$(terraform output -raw prepare_cluster)
TASK=$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$(terraform output -raw prepare_task_definition)" \
  --network-configuration "awsvpcConfiguration={$(terraform output -raw prepare_network)}" \
  --query 'tasks[0].taskArn' --output text)
echo "started $TASK" >&2
while [ "$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" --query 'tasks[0].lastStatus' --output text)" != STOPPED ]; do sleep 30; done
aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
  --query 'tasks[0].{exit:containers[0].exitCode,reason:stoppedReason}' --output text

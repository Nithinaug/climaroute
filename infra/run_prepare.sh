#!/usr/bin/env bash
# Runs the prepare task and waits. Logs: /ecs/climaroute-prepare
set -euo pipefail
cd "$(dirname "$0")"
TASK=$(aws ecs run-task --cluster climaroute --launch-type FARGATE --task-definition climaroute-prepare \
  --network-configuration "awsvpcConfiguration={$(terraform output -raw prepare_network)}" \
  --query 'tasks[0].taskArn' --output text)
echo "started $TASK" >&2
aws ecs wait tasks-stopped --cluster climaroute --tasks "$TASK" || true  # waiter gives up after 10 min
while [ "$(aws ecs describe-tasks --cluster climaroute --tasks "$TASK" --query 'tasks[0].lastStatus' --output text)" != STOPPED ]; do sleep 30; done
aws ecs describe-tasks --cluster climaroute --tasks "$TASK" \
  --query 'tasks[0].{exit:containers[0].exitCode,reason:stoppedReason}' --output text

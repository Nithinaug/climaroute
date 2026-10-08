# One image for every Lambda; each function picks its handler via image_config.
FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ${LAMBDA_TASK_ROOT}/shared/
COPY api/ ${LAMBDA_TASK_ROOT}/api/
COPY pipeline/ ${LAMBDA_TASK_ROOT}/pipeline/
COPY routing/ ${LAMBDA_TASK_ROOT}/routing/
COPY shade/ ${LAMBDA_TASK_ROOT}/shade/
COPY monsoon/__init__.py monsoon/rain.py monsoon/known_flood_spots.geojson ${LAMBDA_TASK_ROOT}/monsoon/

CMD ["api.main.handler"]

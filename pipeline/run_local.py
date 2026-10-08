"""Run the whole shade pipeline without AWS: python -m pipeline.run_local

Same functions as the Step Functions workflow. With DATA_BUCKET set it reads/writes S3.
"""

import json

from pipeline.handlers import merge, shade_tile
from shared.storage import read_bytes

if __name__ == "__main__":
    for tile_id in json.loads(read_bytes("tiles/index.json"))["tiles"]:
        shade_tile({"tile_id": tile_id})
    print(merge())

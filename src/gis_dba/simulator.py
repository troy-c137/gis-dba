"""Generate synthetic XML telemetry and retry transient ingestion failures."""

import argparse
import os
import random
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from xml.etree import ElementTree as ET

from gis_dba import config  # noqa: F401 -- loads .env


def message(asset: int, rng: random.Random) -> bytes:
    root = ET.Element("telemetry")
    data = {
        "message_id": str(uuid4()),
        "equipment_id": f"SIM-ASSET-{asset:03}",
        "observed_at": datetime.now(UTC).isoformat(),
        "longitude": str(-140 + rng.uniform(-0.15, 0.15)),
        "latitude": str(-40 + rng.uniform(-0.15, 0.15)),
        "status": rng.choices(["online", "degraded", "offline"], [90, 8, 2])[0],
        "battery_pct": str(rng.randint(0, 100)),
        "source": "synthetic-simulator",
    }
    for key, value in data.items():
        ET.SubElement(root, key).text = value
    return ET.tostring(root, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate entirely fictional telemetry")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--cycles", type=int, default=0, help="0 runs until Ctrl-C")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.interval < 0 or args.cycles < 0:
        parser.error("interval and cycles must be nonnegative")
    key = os.environ.get("API_KEY")
    if not key:
        parser.error("Set API_KEY in environment or .env")
    rng = random.Random(args.seed)
    cycle = 0
    try:
        while args.cycles == 0 or cycle < args.cycles:
            for asset in range(1, 13):
                raw = message(asset, rng)
                # Reuse identical UUID/content on retry, including after uncertain commits.
                for attempt in range(4):
                    try:
                        req = Request(
                            args.url.rstrip("/") + "/telemetry/xml",
                            data=raw,
                            headers={"Content-Type": "application/xml", "X-API-Key": key},
                        )
                        with urlopen(req, timeout=15) as response:
                            print(response.read().decode())
                        break
                    except HTTPError as exc:
                        if exc.code < 500 or attempt == 3:
                            raise SystemExit(f"Ingestion failed: HTTP {exc.code}") from None
                    except (URLError, TimeoutError):
                        if attempt == 3:
                            raise SystemExit("Ingestion unavailable after four attempts") from None
                    time.sleep(2**attempt)
            cycle += 1
            if args.cycles == 0 or cycle < args.cycles:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

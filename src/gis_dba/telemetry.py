"""Validate the XML telemetry contract before database ingestion."""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from xml.etree import ElementTree as ET

MAX_XML_BYTES = 16_384


class InvalidTelemetry(ValueError):
    pass


@dataclass(frozen=True)
class Telemetry:
    message_id: UUID
    equipment_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    status: str
    battery_pct: int
    source: str

    def parameters(self) -> tuple:
        return (
            self.message_id,
            self.equipment_id,
            self.observed_at,
            self.longitude,
            self.latitude,
            self.status,
            self.battery_pct,
            self.source,
        )


INGEST_SQL = "SELECT tracking.ingest(%s,%s,%s,%s,%s,%s,%s::smallint,%s)"


def parse_xml(raw: bytes) -> Telemetry:
    if len(raw) > MAX_XML_BYTES:
        raise InvalidTelemetry("XML exceeds 16 KiB")
    # Restrict to UTF-8 and ban DTD/entities before ElementTree sees them.
    try:
        text = raw.decode("utf-8")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise InvalidTelemetry("DTD and entity declarations are forbidden")
        root = ET.fromstring(text)
        fields = {
            "message_id",
            "equipment_id",
            "observed_at",
            "longitude",
            "latitude",
            "status",
            "battery_pct",
            "source",
        }
        if root.tag != "telemetry" or root.attrib:
            raise InvalidTelemetry("Expected a telemetry root without attributes")
        if len(root) != len(fields) or {child.tag for child in root} != fields:
            raise InvalidTelemetry("Exactly one of each telemetry field is required")
        if any(child.attrib or len(child) for child in root):
            raise InvalidTelemetry("Fields must contain plain text")
        values = {child.tag: (child.text or "").strip() for child in root}
        observed = datetime.fromisoformat(values["observed_at"].replace("Z", "+00:00"))
        lon, lat = float(values["longitude"]), float(values["latitude"])
        battery = int(values["battery_pct"])
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise InvalidTelemetry("observed_at requires a timezone")
        if observed > datetime.now(UTC) + timedelta(minutes=5):
            raise InvalidTelemetry("observed_at is more than five minutes in the future")
        if not math.isfinite(lon) or not -180 <= lon <= 180:
            raise InvalidTelemetry("longitude must be between -180 and 180")
        if not math.isfinite(lat) or not -90 <= lat <= 90:
            raise InvalidTelemetry("latitude must be between -90 and 90")
        if not re.fullmatch(r"SIM-[A-Z0-9-]{1,60}", values["equipment_id"]):
            raise InvalidTelemetry("equipment_id must be a synthetic SIM- identifier")
        if values["status"] not in {"online", "degraded", "offline"}:
            raise InvalidTelemetry("Invalid status")
        if not 0 <= battery <= 100 or not 1 <= len(values["source"]) <= 80:
            raise InvalidTelemetry("Invalid battery_pct or source")
        return Telemetry(
            UUID(values["message_id"]),
            values["equipment_id"],
            observed,
            lon,
            lat,
            values["status"],
            battery,
            values["source"],
        )
    except (ValueError, ET.ParseError, UnicodeDecodeError) as exc:
        if isinstance(exc, InvalidTelemetry):
            raise
        raise InvalidTelemetry("Malformed XML or invalid field value") from exc

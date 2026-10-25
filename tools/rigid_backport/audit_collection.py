"""Audit two saved, read-only inventory snapshots from one proof process."""

import argparse
import json
import struct
from pathlib import Path

from backport import file_sha
from runtime_inventory import inventory_layout


def verify(before, after):
    for key in ("pid", "game", "game_id", "profile", "player_state", "item_address"):
        if before[key] != after[key]:
            raise ValueError(f"Collection snapshots differ in {key}")
    _, offset = inventory_layout(before["game"])
    expected = int(before["player_state"], 16) + offset
    if int(before["item_address"], 16) != expected:
        raise ValueError("Snapshot uses the wrong native player-state item index")
    for record in (before, after):
        if not record["read_only"] or record["memory_writes"]:
            raise ValueError("Snapshot is not read-only")
        if record["raw"] != f"{record['amount']:08x}{record['capacity']:08x}":
            raise ValueError("Decoded values differ from raw inventory bytes")
        position = record.get("position")
        if position is None:
            # Earlier probe receipts preserved the actor bytes directly.
            actor = bytes.fromhex(record["actor_prefix"])
            offsets = (0x40, 0x50, 0x60) if record["game"] == "prime" else (0x30, 0x40, 0x50)
            position = [struct.unpack_from(">f", actor, x)[0] for x in offsets]
        if not any(abs(v) > 1 for v in position):
            raise ValueError("Snapshot was captured before room initialization")
    if (before["amount"], before["capacity"], after["amount"], after["capacity"]) != (0, 0, 1, 1):
        raise ValueError("Expected native tank amount/capacity 0/0 to 1/1")
    return {
        "game": before["game"],
        "pid": before["pid"],
        "passed": True,
        "amount_delta": 1,
        "capacity_delta": 1,
        "game_memory_writes": False,
        "actuation": "native controller movement through Dolphin TAS input",
    }


def audit(before_path, after_path, output):
    if output.exists():
        raise FileExistsError(output)
    result = verify(json.loads(before_path.read_text()), json.loads(after_path.read_text()))
    result["before"] = {"path": str(before_path), "sha256": file_sha(before_path)}
    result["after"] = {"path": str(after_path), "sha256": file_sha(after_path)}
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    audit(a.before, a.after, a.output)

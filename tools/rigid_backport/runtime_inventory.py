"""Read-only, PID-specific Energy Tank observation for the two audited GC builds."""

import argparse
import ctypes as c
import json
import struct
from pathlib import Path

import psutil

try:
    from retro_data_structures.enums.echoes import PlayerItemEnum
except ImportError:
    from retro_data_structures.enums.echoes import PlayerItem as PlayerItemEnum


def inventory_layout(game):
    if game == "prime":
        return 24, 0x28 + 24 * 8
    if game == "echoes":
        slot = int(PlayerItemEnum.EnergyTank)
        return slot, 0x5C + slot * 12
    raise ValueError("Unsupported inventory game")


class Region(c.Structure):
    _fields_ = [
        ("base", c.c_void_p),
        ("allocation", c.c_void_p),
        ("allocation_protect", c.c_ulong),
        ("partition", c.c_ushort),
        ("size", c.c_size_t),
        ("state", c.c_ulong),
        ("protect", c.c_ulong),
        ("kind", c.c_ulong),
    ]


def snapshot(pid, game, expected_user, output=None, *, quiet=False):
    if output is not None and output.exists():
        raise FileExistsError(output)
    command = psutil.Process(pid).cmdline()
    if "--user" not in command or Path(command[command.index("--user") + 1]).resolve() != expected_user.resolve():
        raise ValueError("PID does not belong to the specified disposable profile")
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = c.c_void_p
    kernel.VirtualQueryEx.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(Region), c.c_size_t]
    kernel.ReadProcessMemory.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p]
    kernel.CloseHandle.argtypes = [c.c_void_p]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise OSError(c.get_last_error())
    if "--exec" not in command:
        raise ValueError("Disposable process does not identify its input disc")
    with Path(command[command.index("--exec") + 1]).open("rb") as image:
        game_id = image.read(6)
    expected_prefix = b"GM8E" if game == "prime" else b"G2ME"
    if len(game_id) != 6 or not game_id.startswith(expected_prefix):
        raise ValueError("Expected audited US GameCube game and region")

    def host_read(address, size):
        buffer = c.create_string_buffer(size)
        if not kernel.ReadProcessMemory(handle, address, buffer, size, None):
            raise OSError(c.get_last_error())
        return buffer.raw

    try:
        address = 0
        region = Region()
        bases = []
        while kernel.VirtualQueryEx(handle, address, c.byref(region), c.sizeof(region)):
            base = region.base or 0
            if region.state == 0x1000 and region.size >= 0x1800000 and region.protect in (4, 8, 0x40, 0x80):
                try:
                    if host_read(base, 6) == game_id:
                        bases.append(base)
                except OSError:
                    pass
            end = base + region.size
            if end <= address:
                break
            address = end
        if not bases:
            raise ValueError("No matching MEM1 mapping")
        base = bases[0]

        def read(address, size):
            if not 0x80000000 <= address <= 0x81800000 - size or not 0 < size <= 4096:
                raise ValueError("Read outside bounded MEM1")
            return host_read(base + address - 0x80000000, size)

        def word(address):
            return int.from_bytes(read(address, 4), "big")

        if game == "prime":
            state_manager = 0x8045A1A8
            wrapper = word(state_manager + 0x8B8)
            player_state = word(wrapper)
            player = word(state_manager + 0x84C)
        else:
            state_manager = 0x803DB6E0
            player_state = word(state_manager + 0x150C)
            player = word(state_manager + 0x14FC)
        slot, offset = inventory_layout(game)
        expected_vtable = 0x803D96E8 if game == "prime" else 0x803B15D0
        if word(player) != expected_vtable:
            raise ValueError("Player vtable differs from the audited GC build")
        raw = read(player_state + offset, 8)
        amount, capacity = struct.unpack(">II", raw)
        if amount > 14 or capacity > 14:
            raise ValueError("Energy Tank values outside native inventory limits")
        translation_offsets = (0x40, 0x50, 0x60) if game == "prime" else (0x30, 0x40, 0x50)
        report = {
            "pid": pid,
            "game": game,
            "game_id": game_id.decode(),
            "profile": str(expected_user),
            "read_only": True,
            "memory_writes": False,
            "player_state": f"{player_state:08X}",
            "item_address": f"{player_state + offset:08X}",
            "amount": amount,
            "capacity": capacity,
            "raw": raw.hex(),
            "matching_mem1_mappings": len(bases),
            "player": f"{player:08X}",
            "position": [struct.unpack(">f", read(player + x, 4))[0] for x in translation_offsets],
            "player_state_item_index": slot,
        }
        forward_offsets = (0x38, 0x48, 0x58) if game == "prime" else (0x28, 0x38, 0x48)
        report["forward"] = [struct.unpack(">f", read(player + x, 4))[0] for x in forward_offsets]
        if game == "echoes":
            marker_address = player_state + 0x5C + 74 * 12
            marker_raw = read(marker_address, 8)
            marker_amount, marker_capacity = struct.unpack(">II", marker_raw)
            report["multiworld_marker"] = {
                "item_index": 74,
                "address": f"{marker_address:08X}",
                "raw": marker_raw.hex(),
                "amount": marker_amount,
                "capacity": marker_capacity,
            }
        if output is not None:
            output.write_text(json.dumps(report, indent=2))
        if not quiet:
            print(json.dumps(report))
        return report
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--game", choices=["prime", "echoes"], required=True)
    p.add_argument("--user", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    snapshot(a.pid, a.game, a.user, a.output)

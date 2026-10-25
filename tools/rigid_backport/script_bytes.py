"""Lossless GC SCLY framing; preserve every original object and connection."""

import struct

from retro_data_structures.game_check import Game


def u32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


def split_objects(data, count, offset, game):
    objects = []
    for _ in range(count):
        header = 5 if game == Game.PRIME else 6
        if offset + header > len(data):
            raise ValueError("Truncated object header")
        size = u32(data, offset + 1) if game == Game.PRIME else struct.unpack_from(">H", data, offset + 4)[0]
        end = offset + header + size
        if size < (8 if game == Game.PRIME else 6) or end > len(data):
            raise ValueError("Invalid object extent")
        objects.append(data[offset:end])
        offset = end
    return objects, offset


def object_info(data, game):
    if game == Game.PRIME:
        kind, identity, count = data[0], u32(data, 5), u32(data, 9)
        start = 13 + 12 * count
    else:
        kind, identity, count = data[:4].decode("ascii"), u32(data, 6), struct.unpack_from(">H", data, 10)[0]
        start = 12 + 12 * count
    if start > len(data):
        raise ValueError("Connections exceed object extent")
    return kind, identity, data[start:]


def split_prime_scly(data):
    if data[:4] != b"SCLY":
        raise ValueError("Expected SCLY")
    count = u32(data, 8)
    if count > 64 or 12 + 4 * count > len(data):
        raise ValueError("Invalid layer count")
    layers, cursor = [], 12 + 4 * count
    for i in range(count):
        size = u32(data, 12 + 4 * i)
        layer = data[cursor : cursor + size]
        objects, end = split_objects(layer, u32(layer, 1), 5, Game.PRIME)
        layers.append((layer[:1], objects, layer[end:]))
        cursor += size
    if cursor > len(data):
        raise ValueError("Layers exceed section")
    return data[:8], layers, data[cursor:]


def add_object(data, obj, game, layer=0):
    if game == Game.PRIME:
        prefix, layers, tail = split_prime_scly(data)
        blobs = []
        for i, (unknown, objects, padding) in enumerate(layers):
            values = objects + ([obj] if i == layer else [])
            blobs.append(unknown + struct.pack(">I", len(values)) + b"".join(values) + padding)
        result = (
            prefix
            + struct.pack(">I", len(blobs))
            + struct.pack(">" + "I" * len(blobs), *map(len, blobs))
            + b"".join(blobs)
            + tail
        )
        # Prove no original object bytes or connections were rewritten.
        _, checked, _ = split_prime_scly(result)
        for i, (_, objects, _) in enumerate(layers):
            if checked[i][1][: len(objects)] != objects:
                raise ValueError("Original scripts changed")
        return result
    if data[:4] != b"SCLY" or data[9] != 1:
        raise ValueError("Unexpected Echoes SCLY header")
    objects, end = split_objects(data, u32(data, 10), 14, game)
    result = data[:10] + struct.pack(">I", len(objects) + 1) + b"".join(objects) + obj + data[end:]
    checked, _ = split_objects(result, len(objects) + 1, 14, game)
    if checked[:-1] != objects:
        raise ValueError("Original scripts changed")
    return result


def make_object(kind, identity, props, game):
    if game == Game.PRIME:
        body = struct.pack(">II", identity, 0) + props
        return struct.pack(">BI", kind, len(body)) + body
    body = struct.pack(">IH", identity, 0) + props
    return kind.encode("ascii") + struct.pack(">H", len(body)) + body

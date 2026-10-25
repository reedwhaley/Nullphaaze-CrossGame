"""Bounded, asset-only Corruption pickup backport for GC Prime/Echoes.

Uses a rigid bind pose and native Prime TEV templates. No animation or particles.
Game data is read from user-provided extractions and is never bundled with code.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

from construct import Container, ListContainer
from retro_data_structures.asset_manager import AssetManager
from retro_data_structures.base_resource import RawResource
from retro_data_structures.file_provider import PathFileProvider
from retro_data_structures.formats.cmdl import Cmdl
from retro_data_structures.formats.pak import Pak
from retro_data_structures.formats.pak_common import PakBody
from retro_data_structures.formats.txtr import Txtr
from retro_data_structures.game_check import Game

SOURCE_MODEL = 0x8F865363AED3AFE6
SOURCE_CHARACTER = 0x778E1ABA10D9B9E0
TEMPLATE_MODEL = 0x86908399
NAME = "prime3_EnergyTank_Static"
PROFILES = {
    "energy-tank": (SOURCE_MODEL, SOURCE_CHARACTER, NAME),
    "hyper-missile": (0x6FF70067566550DA, 0xA5534CB39EE8D90F, "prime3_HyperMissile_Static"),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def allocate(kind, identity, target, occupied):
    """Deterministic 32-bit ID; reject collisions, never truncate source IDs."""
    value = int.from_bytes(
        hashlib.sha256(f"corruption-backport-v1/{target.name}/{kind}/{identity:016X}".encode()).digest()[:4], "big"
    )
    if value in occupied or value in (0, 0xFFFFFFFF):
        raise ValueError(f"Asset ID collision: {value:08X}")
    occupied.add(value)
    return value


def checked_material(source, templates, texture_ids, game, index, profile="energy-tank"):
    if profile not in PROFILES:
        raise ValueError("Unsupported source profile")
    passes = [e.body for e in source.elements if e.type == "PASS"]
    roles = [p.subtype for p in passes]
    if roles == ["CLR ", "INCA"] and source.flags == 129:
        result = copy.deepcopy(templates[0])
    elif roles == ["INCA"] and source.flags == 161:
        result = copy.deepcopy(templates[1])
    else:
        raise ValueError("Unsupported source material roles/blending")
    if source.vertex_attribute_flags != 0x8100030F:
        raise ValueError("Unsupported source vertex layout")
    hyper = profile == "hyper-missile"
    expected = [("PASS", role) for role in roles] + [("INT ", "BNIF"), ("CLR ", "CLR "), ("END ", None)]
    if hyper:
        expected.insert(len(roles), ("INT ", "BLOD"))
    if [(e.type, e.body.subtype if e.body is not None else None) for e in source.elements] != expected:
        raise ValueError("Unknown material operation")
    integers = {e.body.subtype: e.body.value for e in source.elements if e.type == "INT "}
    if integers != ({"BLOD": 0, "BNIF": 153} if hyper else {"BNIF": 32}):
        raise ValueError("Unknown bloom configuration")
    for p in passes:
        if p.uv_animation or p.uv_source != 0 or p.flags != (0 if p.subtype == "CLR " else (6 if hyper else 4)):
            raise ValueError("Animated or unsupported source pass")
    result.group_index = index
    result.texture_indices = ListContainer(texture_ids.index(p.id) for p in passes)
    result.vertex_attribute_flags = 0x30F | (0x81000000 if game == Game.ECHOES else 0)
    result.flags = (result.flags | 0x3000) if game == Game.ECHOES else (result.flags | 1) & ~0x3000
    result.unk_1 = result.unk_2 = 0 if game == Game.ECHOES else None
    # Both source passes use UV0. Keep two generators for the two TEV stages,
    # but select UV0 for both instead of requiring an absent second UV stream.
    result.texgen_flags = ListContainer([templates[0].texgen_flags[0]] * len(passes))
    tint = next(e.body.value for e in source.elements if e.type == "CLR ")
    if roles == ["CLR ", "INCA"] and tint != 255:
        raise ValueError("Unsupported diffuse/emission tint")
    if roles == ["INCA"]:
        # GX_CC_KONST = 14, GX_KCSEL_K0 = 12. Multiply texture RGB by K0.
        result.flags |= 8
        result.konst_colors = ListContainer([tint])
        stage = result.tev_stages[0]
        stage.color_input_flags = (stage.color_input_flags & ~(31 << 5)) | (14 << 5)
        stage.konst_color_input = 12
    return result


def convert_mesh(source, templates, game, target_texture_ids, profile="energy-tank"):
    if game not in (Game.PRIME, Game.ECHOES):
        raise ValueError("Target must be GameCube Prime or Echoes")
    if source.version != 5 or source.flags != 1 or len(source.material_sets) != 1:
        raise ValueError("Unsupported source CMDL")
    raw = copy.deepcopy(source)
    textures = list(
        dict.fromkeys(p.body.id for m in source.material_sets[0].materials for p in m.elements if p.type == "PASS")
    )
    if set(textures) != set(target_texture_ids):
        raise ValueError("Incomplete texture mapping")
    raw.version = 2 if game == Game.PRIME else 4
    # The result is static: no external skin/skeleton and no matrix palette.
    raw.flags &= ~1
    raw.material_sets = ListContainer(
        [
            Container(
                texture_file_ids=ListContainer(target_texture_ids[t] for t in textures),
                materials=ListContainer(
                    checked_material(m, templates, textures, game, i, profile)
                    for i, m in enumerate(source.material_sets[0].materials)
                ),
            )
        ]
    )
    for surface in raw.surfaces:
        if surface.header.material_index >= len(raw.material_sets[0].materials):
            raise ValueError("Surface material outside material set")
        surface.header.unk_1 = surface.header.unk_2 = 0 if game == Game.ECHOES else None
        surface.header.extra_data = b""
        for primitive in surface.primitives:
            if primitive.type == 0 and not primitive.vertices:
                continue  # display-list alignment parsed as empty commands
            if primitive.type not in (0x80, 0x90, 0x98, 0xA0):
                raise ValueError("Unsupported primitive command")
            for vertex in primitive.vertices:
                if vertex.matrix.position != 0 or vertex.matrix.tex["6"] != 0:
                    raise ValueError("Non-rigid matrix palette")
                if not (
                    0 <= vertex.position < len(raw.attrib_arrays.positions)
                    and 0 <= vertex.normal < len(raw.attrib_arrays.normals)
                    and 0 <= vertex.tex["0"] < len(raw.attrib_arrays.uvs)
                ):
                    raise ValueError("Vertex attribute index out of range")
                vertex.matrix.position = vertex.matrix.tex["6"] = 0 if game == Game.ECHOES else None
    for points in (raw.attrib_arrays.positions, raw.attrib_arrays.normals, raw.attrib_arrays.uvs):
        if any(not math.isfinite(v) for p in points for v in p):
            raise ValueError("Non-finite mesh attribute")
    data = Cmdl(raw, game).build()
    checked = Cmdl.parse(data, game)._raw

    def geometry(m):
        return [
            (
                s.header.material_index,
                [
                    (p.type, [(v.position, v.normal, v.tex["0"]) for v in p.vertices])
                    for p in s.primitives
                    if p.vertices
                ],
            )
            for s in m.surfaces
        ]

    if geometry(checked) != geometry(source):
        raise ValueError("Display-list geometry changed during conversion")
    for field in ("positions", "normals", "uvs"):
        original = raw.attrib_arrays[field]
        actual = checked.attrib_arrays[field]
        # Attribute sections contain alignment padding interpreted as extra values.
        if actual[: len(original)] != original:
            raise ValueError(f"{field} changed during serialization")
    return data


def export(source_path, prime_path, target_path, game, output, profile="energy-tank"):
    if game not in (Game.PRIME, Game.ECHOES):
        raise ValueError("Target must be GameCube Prime or Echoes")
    paths = [p.resolve() for p in (source_path, prime_path, target_path)]
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in paths):
        raise ValueError("Use a new output directory disjoint from all inputs")
    source_model, source_character, name = PROFILES[profile]
    source = AssetManager(PathFileProvider(source_path), Game.CORRUPTION)
    prime = AssetManager(PathFileProvider(prime_path), Game.PRIME)
    target = AssetManager(PathFileProvider(target_path), game)
    character = source.get_parsed_asset(source_character)._raw
    if character.model_id != source_model:
        raise ValueError("Source character/model association changed")
    skin = source.get_parsed_asset(character.skin_id)._raw
    skeleton = source.get_parsed_asset(character.skeleton_id)._raw
    if len(skin.vertex_groups) != 1 or [(w.bone_id, w.weight) for w in skin.vertex_groups[0].weights_array] != [
        (2, 1.0)
    ]:
        raise ValueError("Source skin is not the audited rigid pickup")
    if any(
        any(b.position)
        or any(abs(v - expected) > 1e-7 for q in (b.rotation, b.local_rotation) for v, expected in zip(q, [1, 0, 0, 0]))
        for b in skeleton.bones
    ):
        raise ValueError("Bind-pose transforms require baking")
    mesh = source.get_parsed_asset(source_model)._raw
    textures = list(
        dict.fromkeys(p.body.id for m in mesh.material_sets[0].materials for p in m.elements if p.type == "PASS")
    )
    occupied = set(target.all_asset_ids())
    texture_map = {t: allocate("TXTR", t, game, occupied) for t in textures}
    model_id = allocate("CMDL", source_model, game, occupied)
    resources = {}
    source_resources = {}
    for identity in (source_character, character.skin_id, character.skeleton_id, source_model, *textures):
        resource = source.get_raw_asset(identity)
        source_resources[f"{identity:016X}"] = {"type": resource.type, "sha256": sha(resource.data)}
    for old, new in texture_map.items():
        resource = source.get_raw_asset(old)
        if resource.type != "TXTR":
            raise ValueError("Texture reference resolves to wrong type")
        # The audited GX texture formats are shared by these games.
        texture = Txtr.parse(resource.data, Game.CORRUPTION)
        if texture._raw.header.format not in range(11):
            raise ValueError("Unsupported texture format")
        Txtr.parse(resource.data, game)
        resources[new] = RawResource("TXTR", resource.data)
    templates = prime.get_parsed_asset(TEMPLATE_MODEL)._raw.material_sets[0].materials
    resources[model_id] = RawResource("CMDL", convert_mesh(mesh, templates, game, texture_map, profile))
    input_files = set()
    for identity in (source_character, character.skin_id, character.skeleton_id, source_model, *textures):
        input_files.update(source_path / "files" / p for p in source.find_paks(identity))
    input_files.update(prime_path / "files" / p for p in prime.find_paks(TEMPLATE_MODEL))
    before = {str(p): file_sha(p) for p in input_files}
    output.mkdir(parents=True)
    pak = Pak(PakBody([], []), game)
    for identity, resource in resources.items():
        (output / f"{identity}.{resource.type}").write_bytes(resource.data)
        pak.add_asset(identity, resource)
    binary = pak.build()
    (output / "assets.pak").write_bytes(binary)
    reread = Pak.parse(binary, game)
    if {i for i, _ in reread.get_all_assets()} != set(resources):
        raise ValueError("PAK asset inventory changed")
    for identity, actual in reread.get_all_assets():
        expected = resources[identity]
        if (
            actual.type != expected.type
            or actual.data[: len(expected.data)] != expected.data
            or actual.data[len(expected.data) :] != b"\xff" * ((-len(expected.data)) % 32)
        ):
            raise ValueError("PAK asset roundtrip failed")
    deps = [{"type": r.type, "id": i} for i, r in resources.items()]
    metadata = {
        "version": 1,
        "profile": profile,
        "items": {name: {"cmdl": model_id, "ancs": 0xFFFFFFFF, "character": 0, "scale": 1.5}},
        "new_assets": [
            {"old_id": old, "new_id": new, "type": "TXTR", "dependencies": []} for old, new in texture_map.items()
        ]
        + [{"old_id": source_model, "new_id": model_id, "type": "CMDL", "dependencies": deps[:-1]}],
    }
    (output / "meta.json").write_text(json.dumps(metadata, indent=2))
    after = {str(p): file_sha(p) for p in input_files}
    if before != after:
        raise ValueError("Source input changed")
    report = {
        "phase": f"corruption-static-{profile}-backport-v1",
        "item": profile,
        "bind_rotation_tolerance": 1e-7,
        "target": game.name,
        "python": __import__("sys").version,
        "rds": importlib.metadata.version("retro-data-structures"),
        "source_resources": source_resources,
        "source_files": before,
        "source_unchanged": True,
        "template_sha256": sha(prime.get_raw_asset(TEMPLATE_MODEL).data),
        "model_id": model_id,
        "texture_map": {f"{k:016X}": v for k, v in texture_map.items()},
        "positions": len(mesh.attrib_arrays.positions),
        "surfaces": len(mesh.surfaces),
        "static_bind_pose": True,
        "particles": False,
        "animation": False,
        "exact_shading": False,
        "shading_limitations": [
            "Corruption bloom omitted; diffuse/emission mapped to native GX TEV",
            "Emission tint mapped to GX konst color; visual acceptance required",
        ],
        "binary_roundtrip_passed": True,
        "gameplay_verified": False,
        "outputs": {p.name: file_sha(p) for p in output.iterdir() if p.is_file()},
    }
    (output / "conversion-report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--prime", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--game", required=True, choices=["prime", "echoes"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--item", choices=list(PROFILES), default="energy-tank")
    args = parser.parse_args()
    report = export(
        args.source,
        args.prime,
        args.target,
        Game.PRIME if args.game == "prime" else Game.ECHOES,
        args.output,
        args.item,
    )
    print(json.dumps({"target": report["target"], "output": str(args.output), "passed": True}))


if __name__ == "__main__":
    main()

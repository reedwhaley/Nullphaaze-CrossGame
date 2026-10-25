"""Create disposable GC test discs with a static Corruption tank near first spawn."""

import argparse
import copy
import hashlib
import io
import json
import os
import struct
from pathlib import Path

import nod
from backport import NAME, file_sha
from retro_data_structures.asset_manager import AssetManager
from retro_data_structures.base_resource import Dependency, RawResource
from retro_data_structures.enums.echoes import PlayerItemEnum
from retro_data_structures.file_provider import IsoFileProvider, PathFileProvider
from retro_data_structures.formats.mlvl import Mlvl
from retro_data_structures.formats.mrea import AreaDependencies, Mrea, MREAHeader
from retro_data_structures.formats.pak import Pak
from retro_data_structures.game_check import Game
from retro_data_structures.properties.echoes.core.Vector import Vector
from retro_data_structures.properties.echoes.objects.Pickup import Pickup
from script_bytes import add_object, make_object, object_info, split_objects, split_prime_scly, u32


def validate_gc_image(image, staging):
    disc, is_wii = nod.open_disc_from_image(image)
    if is_wii:
        raise ValueError("Expected GameCube disc")
    partition = disc.get_data_partition()
    if partition is None:
        raise ValueError("Disc has no data partition")
    provider = IsoFileProvider(image)
    files = {
        p.relative_to(staging / "files").as_posix(): file_sha(p) for p in (staging / "files").rglob("*") if p.is_file()
    }
    if set(provider.get_file_list()) != set(files):
        raise ValueError("Disc file inventory differs from staging")
    padded = []
    for name, digest in files.items():
        actual = provider.read_binary(name)
        size = (staging / "files" / name).stat().st_size
        if (
            file_sha_bytes(actual[:size]) != digest
            or len(actual) - size not in (0, (-size) % 32)
            or actual[size:] != b"\xff" * (len(actual) - size)
        ):
            raise ValueError(f"Disc file differs from staging: {name}")
        if len(actual) != size:
            padded.append(name)
    if provider.get_dol() != (staging / "sys/main.dol").read_bytes():
        raise ValueError("Disc DOL differs from staging")
    return {
        "format": "GameCube",
        "files_checked": len(files),
        "all_staged_payloads_match": True,
        "dol_matches": True,
        "nod_alignment": "At most 31 FF bytes appended to non-aligned FST files",
        "padded_files": padded,
    }


def prime_pickup(template, model, position):
    props = bytearray(template)
    start = props.index(0, 4) + 1
    struct.pack_into(">fff", props, start, *position)
    struct.pack_into(">fff", props, start + 12, 0, 0, 0)
    struct.pack_into(">fff", props, start + 24, 1.5, 1.5, 1.5)
    struct.pack_into(">III", props, start + 60, 24, 1, 1)
    struct.pack_into(">fff", props, start + 72, 100, 0, 0)
    struct.pack_into(">IIII", props, start + 84, model, 0xFFFFFFFF, 0, 0)
    props[-9:] = struct.pack(">BfI", 1, 0, 0xFFFFFFFF)
    # Clone only has one non-animation asset reference: the missile scan.
    scan = struct.pack(">I", 0xBA1EB6DD)
    if props.count(scan) != 1:
        raise ValueError("Audited pickup scan reference changed")
    props = props.replace(scan, b"\xff" * 4)
    return bytes(props)


def echoes_pickup(model, position, template, name=NAME):
    p = copy.deepcopy(template)
    p.editor_properties.name = name
    p.editor_properties.active = True
    p.editor_properties.transform.position = Vector(*position)
    p.editor_properties.transform.scale = Vector(1.5, 1.5, 1.5)
    p.item_to_give = PlayerItemEnum.EnergyTank
    p.capacity_increase = p.amount = 1
    p.model = model
    p.animation_information.ancs = 0xFFFFFFFF
    p.actor_information.scannable.scannable_info0 = 0xFFFFFFFF
    p.pickup_effect = 0xFFFFFFFF
    p.item_percentage_increase = 0
    p.auto_spin = False
    data = p.to_bytes()
    if Pickup.from_bytes(data).to_bytes() != data:
        raise ValueError("Echoes pickup property roundtrip failed")
    return data


def replace_script(raw, obj, game):
    parsed = Mrea.parse(raw, game)
    old_sections = copy.deepcopy(parsed._raw.raw_sections)
    script = parsed._raw.raw_sections.script_layers_section
    result = add_object(script[0], obj, game)
    script[0] = result + bytes((-len(result)) % 32)
    if game == Game.PRIME:
        stream = io.BytesIO(raw)
        header = MREAHeader.parse_stream(stream, target_game=game)
        sections = []
        for size in header.data_section_sizes:
            sections.append(stream.read(size))
            stream.seek((-size) % 32, 1)
        index = header.section_index.script_layers_section
        sections[index] = script[0]
        header.data_section_sizes = [len(s) for s in sections]
        encoded = MREAHeader.build(header, target_game=game) + b"".join(s + bytes((-len(s)) % 32) for s in sections)
    else:
        encoded = parsed.build()
    checked = Mrea.parse(encoded, game)
    for category, values in old_sections.items():
        if category != "script_layers_section" and checked._raw.raw_sections[category] != values:
            raise ValueError(f"Unrelated MREA category changed: {category}")
    original = old_sections.script_layers_section
    rebuilt = checked._raw.raw_sections.script_layers_section
    if original[1:] != rebuilt[1:]:
        raise ValueError("Unrelated script layers changed")
    return encoded


def build(target_path, assets_path, game, output):
    target_path, assets_path, output = [p.resolve() for p in (target_path, assets_path, output)]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in (target_path, assets_path)):
        raise ValueError("Output must be new and disjoint from inputs")
    metadata = json.loads((assets_path / "meta.json").read_text())
    if len(metadata["items"]) != 1:
        raise ValueError("Proof requires exactly one item")
    name, item = next(iter(metadata["items"].items()))
    model = item["cmdl"]
    profile = metadata.get("profile", "energy-tank")
    if profile not in ("energy-tank", "hyper-missile"):
        raise ValueError("Unsupported proof profile")
    manager = AssetManager(PathFileProvider(target_path), game)
    imported = {
        r["new_id"]: RawResource(r["type"], (assets_path / f"{r['new_id']}.{r['type']}").read_bytes())
        for r in metadata["new_assets"]
    }
    if set(imported) & set(manager.all_asset_ids()):
        raise ValueError("Target asset ID collision")
    deps = tuple(Dependency(r.type, i) for i, r in imported.items())
    worlds = (
        [(0x158EFE17, 0xD1241219, (-87.9, 220.4, 1.5)), (0x39F2DE28, 0xB2701146, (-366.2, 375.8, -20.8))]
        if game == Game.PRIME
        else [(0x3BFA3EFF, 0x62B0D67D, (-102.65, -184.47, -47.0))]
    )
    template = None
    if game == Game.PRIME:
        landing = Mrea.parse(manager.get_raw_asset(0xB2701146).data, game)
        objects = split_prime_scly(landing._raw.raw_sections.script_layers_section[0])[1][0][1]
        template = next(object_info(o, game)[2] for o in objects if object_info(o, game)[:2] == (0x11, 0x7E))
    else:
        # Preserve retail collision, lighting and visibility settings. The
        # generated defaults are not a substitute for native pickup behavior.
        world = manager.get_parsed_asset(0x3BFA3EFF)
        native = next(a for a in world.areas if a.name == "Hive Chamber A")
        raw = Mrea.parse(manager.get_raw_asset(native.mrea_asset_id).data, game)
        template = next(
            Pickup.from_bytes(object_info(o, game)[2])
            for s in raw._raw.raw_sections.script_layers_section
            for o in split_objects(s, u32(s, 10), 14, game)[0]
            if object_info(o, game)[0] == "PCKP"
        )
    changes = {}
    room_reports = []
    for world_id, area_id, position in worlds:
        world = manager.get_parsed_asset(world_id)
        original_world = copy.deepcopy(world._raw)
        world.get_area(area_id)
        index = next(i for i, a in enumerate(world._raw.areas) if a.area_mrea_id == area_id)
        mrea = manager.get_raw_asset(area_id)
        raw = Mrea.parse(mrea.data, game)._raw.raw_sections.script_layers_section[0]
        all_objects = (
            [o for _, objects, _ in split_prime_scly(raw)[1] for o in objects]
            if game == Game.PRIME
            else split_objects(raw, u32(raw, 10), 14, game)[0]
        )
        identity = (index << 16) | 0xFDF0
        if identity in {object_info(o, game)[1] for o in all_objects}:
            raise ValueError("Test object ID collision")
        props = (
            prime_pickup(template, model, position)
            if game == Game.PRIME
            else echoes_pickup(model, position, template, name)
        )
        obj = make_object(0x11 if game == Game.PRIME else "PCKP", identity, props, game)
        edited = replace_script(mrea.data, obj, game)
        old = world._raw.areas[index].dependencies
        layers = list(old.layers)
        layers[0] = layers[0] + deps
        world._raw.areas[index].dependencies = AreaDependencies(tuple(layers), old.non_layer)
        if game == Game.PRIME:
            # RDS's unnamed retail empty-string field requires an explicit build value.
            world._raw[None] = ""
        changed_world = world.build()
        checked_world = Mlvl.parse(changed_world, game)._raw
        checked_world.areas[index].dependencies = original_world.areas[index].dependencies
        if checked_world != original_world:
            raise ValueError("MLVL changed beyond test-room dependencies")
        for rid, resource in [(world_id, RawResource("MLVL", changed_world)), (area_id, RawResource("MREA", edited))]:
            for pak in manager.find_paks(rid):
                changes.setdefault(pak, {})[rid] = resource
        for pak in manager.find_paks(area_id):
            changes[pak].update(imported)
        room_reports.append(
            {
                "world": f"{world_id:08X}",
                "area": f"{area_id:08X}",
                "instance": f"{identity:08X}",
                "position": position,
                "model": f"{model:08X}",
                "layer": 0,
                "original_object_bytes_preserved": True,
                "grant": "native Energy Tank +1",
                "animation_set": "FFFFFFFF",
                "particles": "FFFFFFFF",
            }
        )
    source_files = {p.relative_to(target_path).as_posix(): file_sha(p) for p in target_path.rglob("*") if p.is_file()}
    output.mkdir(parents=True)
    staging = output / "disc"
    staging.mkdir()
    for pak_name, resources in changes.items():
        pak = Pak.parse((target_path / "files" / pak_name).read_bytes(), game)
        originals = {i: (r.type, file_sha_bytes(r.data)) for i, r in pak.get_all_assets()}
        for identity, resource in resources.items():
            if identity in originals:
                pak.replace_asset(identity, resource)
            else:
                pak.add_asset(identity, resource)
        path = staging / "files" / pak_name
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = pak.build()
        path.write_bytes(encoded)
        checked = Pak.parse(encoded, game)
        actual = {i: (r.type, file_sha_bytes(r.data)) for i, r in checked.get_all_assets()}
        for identity, original in originals.items():
            if identity not in resources and actual[identity] != original:
                raise ValueError("Unrelated PAK resource changed")
        if set(actual) != set(originals) | set(resources):
            raise ValueError("PAK resource population changed")
    for relative in source_files:
        source = target_path / relative
        destination = staging / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, destination)
    image = output / f"{game.name.lower()}-corruption-{profile}.iso"
    if nod.DiscBuilderGCN.calculate_total_size_required(staging) is None:
        raise ValueError("Proof exceeds GameCube disc capacity")
    builder = nod.DiscBuilderGCN(image, lambda *_: None)
    builder.build_from_directory(staging)
    with image.open("rb") as stream:
        if stream.read(0x20)[0x18:0x20] != bytes.fromhex("00000000c2339f3d"):
            raise ValueError("Packager did not produce a GameCube disc")
    disc_validation = validate_gc_image(image, staging)
    after = {p.relative_to(target_path).as_posix(): file_sha(p) for p in target_path.rglob("*") if p.is_file()}
    if after != source_files:
        raise ValueError("Original extraction changed")
    report = {
        "game": game.name,
        "item": profile,
        "fixture_grant": "native Energy Tank",
        "source": str(target_path),
        "source_files": source_files,
        "source_unchanged": True,
        "asset_export": str(assets_path),
        "rooms": room_reports,
        "changed_paks": sorted(changes),
        "unrelated_pak_resources_unchanged": True,
        "unrelated_room_sections_unchanged": True,
        "nod_pack": True,
        "disc_validation": disc_validation,
        "image": str(image),
        "image_sha256": file_sha(image),
        "gameplay_verified": False,
    }
    (output / "proof-build-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"image": str(image), "passed": True}))


def file_sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--game", choices=["prime", "echoes"], required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    build(a.target, a.assets, Game.PRIME if a.game == "prime" else Game.ECHOES, a.output)

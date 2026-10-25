"""Synthetic safety tests; no game data required."""

import copy
import struct
import tempfile
import unittest
from pathlib import Path

import pytest
from audit_collection import verify
from backport import allocate, checked_material, convert_mesh, export
from build_proof import echoes_pickup
from construct import Container as C
from construct import ListContainer as L
from retro_data_structures.enums.echoes import InventorySlotEnum, PlayerItemEnum
from retro_data_structures.game_check import Game
from retro_data_structures.properties.echoes.core.Vector import Vector
from retro_data_structures.properties.echoes.objects.Pickup import Pickup
from runtime_inventory import inventory_layout
from script_bytes import add_object, make_object, object_info, split_objects, split_prime_scly, u32


class ScriptTests(unittest.TestCase):
    def test_prime_connections_preserved_as_u32(self):
        body = struct.pack(">IIIII", 0x1234, 1, 0x11223344, 0x55667788, 0x99AABBCC) + b"owned properties"
        obj = struct.pack(">BI", 0x11, len(body)) + body
        assert object_info(obj, Game.PRIME) == (17, 4660, b"owned properties")
        layer = b"\0" + struct.pack(">I", 1) + obj
        source = b"SCLY" + struct.pack(">III", 0, 1, len(layer)) + layer
        new = make_object(0x11, 0x4321, b"new properties", Game.PRIME)
        out = add_object(source, new, Game.PRIME)
        assert split_prime_scly(out)[1][0][1] == [obj, new]

    def test_echoes_connections_preserved(self):
        body = struct.pack(">I H III", 123, 1, 0x41424344, 0x45464748, 456) + b"owned props"
        obj = b"PCKP" + struct.pack(">H", len(body)) + body
        source = b"SCLY\0" + struct.pack(">I", 0) + b"\1" + struct.pack(">I", 1) + obj
        new = make_object("PCKP", 321, b"new props", Game.ECHOES)
        result = add_object(source, new, Game.ECHOES)
        assert split_objects(result, u32(result, 10), 14, Game.ECHOES)[0] == [obj, new]
        assert object_info(obj, Game.ECHOES)[2] == b"owned props"

    def test_truncated_object_rejected(self):
        obj = make_object(0x11, 123, b"owned", Game.PRIME)
        for i in range(len(obj)):
            with pytest.raises((ValueError, struct.error)):
                split_objects(obj[:i], 1, 0, Game.PRIME)

    def test_connections_cannot_overrun_object(self):
        obj = make_object(0x11, 123, b"", Game.PRIME)
        obj = obj[:9] + struct.pack(">I", 1)
        with pytest.raises(ValueError, match="Connections exceed"):
            object_info(obj, Game.PRIME)


class ConversionTests(unittest.TestCase):
    def test_collection_receipt_requires_same_native_field_and_process(self):
        before = {
            "pid": 123,
            "game": "echoes",
            "game_id": "G2ME01",
            "profile": "owned-test",
            "player_state": "80001000",
            "item_address": "80001254",
            "read_only": True,
            "memory_writes": False,
            "position": [-100, -180, -48],
            "amount": 0,
            "capacity": 0,
            "raw": "0000000000000000",
        }
        after = dict(before, amount=1, capacity=1, raw="0000000100000001")
        assert verify(before, after)["passed"]
        with pytest.raises(ValueError, match="pid"):
            verify(before, dict(after, pid=124))
        wrong_before = dict(before, item_address="800011DC")
        wrong_after = dict(after, item_address="800011DC")
        with pytest.raises(ValueError, match="wrong native"):
            verify(wrong_before, wrong_after)

    def test_output_cannot_overlap_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            marker = source / "marker"
            marker.write_bytes(b"owned immutable input")
            with pytest.raises(ValueError, match="disjoint"):
                export(source, root / "prime", root / "target", Game.PRIME, source / "output")
            assert marker.read_bytes() == b"owned immutable input"
            assert not (source / "output").exists()

    def test_echoes_inventory_and_pickup_ids_are_distinct(self):
        assert int(PlayerItemEnum.EnergyTank) == 42
        assert int(InventorySlotEnum.EnergyTank) == 32
        assert inventory_layout("echoes") == (42, 0x254)
        assert inventory_layout("prime") == (24, 0xE8)

    def test_echoes_clone_preserves_native_collision_and_lighting(self):
        template = Pickup()
        template.collision_size = Vector(1, 1, 2)
        template.collision_offset = Vector(0, 0, 1)
        template.actor_information.lighting.num_area_lights = 4
        before = copy.deepcopy(template)
        output = Pickup.from_bytes(echoes_pickup(123, (1, 2, 3), template))
        assert output.collision_size == template.collision_size
        assert output.collision_offset == template.collision_offset
        assert output.actor_information.lighting == template.actor_information.lighting
        assert output.capacity_increase == output.amount == 1
        assert output.item_to_give == PlayerItemEnum.EnergyTank
        assert output.animation_information.ancs == 0xFFFFFFFF
        assert template == before

    def test_hyper_material_is_explicit_and_bloom_is_bounded(self):
        source = self.material()
        source.elements[1].body.flags = 6
        source.elements.insert(2, C(type="INT ", body=C(subtype="BLOD", value=0)))
        source.elements[3].body.value = 153
        template = C(flags=1, texgen_flags=L([0]))
        for game in (Game.PRIME, Game.ECHOES):
            result = checked_material(source, [template], [100, 101], game, 0, "hyper-missile")
            assert result.texture_indices == [0, 1]
        with pytest.raises(ValueError, match="operation"):
            checked_material(source, [template], [100, 101], Game.PRIME, 0)
        source.elements[2].body.value = 1
        with pytest.raises(ValueError, match="bloom"):
            checked_material(source, [template], [100, 101], Game.PRIME, 0, "hyper-missile")
        with pytest.raises(ValueError, match="profile"):
            checked_material(source, [template], [100, 101], Game.PRIME, 0, "unknown")

    def material(self, roles=("CLR ", "INCA"), flags=129):
        return C(
            flags=flags,
            vertex_attribute_flags=0x8100030F,
            elements=L(
                [
                    C(
                        type="PASS",
                        body=C(subtype=r, id=i + 100, uv_source=0, uv_animation=[], flags=0 if r == "CLR " else 4),
                    )
                    for i, r in enumerate(roles)
                ]
                + [
                    C(type="INT ", body=C(subtype="BNIF", value=32)),
                    C(type="CLR ", body=C(subtype="CLR ", value=255 if flags == 129 else 0x666666FF)),
                    C(type="END ", body=None),
                ]
            ),
        )

    def templates(self):
        template = C(
            flags=0x31083,
            konst_colors=None,
            texgen_flags=L([2014272, 2014288]),
            tev_stages=L(
                [C(color_input_flags=500047, konst_color_input=0), C(color_input_flags=12559, konst_color_input=0)]
            ),
        )
        return [template, copy.deepcopy(template)]

    def test_ids_are_stable_and_target_specific(self):
        a = allocate("CMDL", 2**60, Game.PRIME, set())
        assert a == allocate("CMDL", 2**60, Game.PRIME, set())
        assert a != allocate("CMDL", 2**60, Game.ECHOES, set())
        assert a < 2**32
        with pytest.raises(ValueError, match="Asset ID collision"):
            allocate("CMDL", 2**60, Game.PRIME, {a})

    def test_uv0_is_used_for_both_passes(self):
        source = self.material()
        before = copy.deepcopy(source)
        out = checked_material(source, self.templates(), [100, 101], Game.PRIME, 0)
        assert out.texgen_flags == [2014272, 2014272]
        assert out.texture_indices == [0, 1]
        assert out.vertex_attribute_flags == 783
        assert source == before

    def test_echoes_matrix_flags(self):
        out = checked_material(self.material(), self.templates(), [100, 101], Game.ECHOES, 0)
        assert out.vertex_attribute_flags == 2164261647
        assert out.unk_1 == 0

    def test_emission_tint_uses_konst(self):
        out = checked_material(self.material(("INCA",), 161), self.templates(), [100], Game.PRIME, 1)
        assert out.konst_colors == [1717987071]
        assert out.tev_stages[0].color_input_flags >> 5 & 31 == 14
        assert out.tev_stages[0].konst_color_input == 12

    def test_unsupported_materials_rejected(self):
        cases = []
        m = self.material()
        m.flags |= 8
        cases.append(m)
        m = self.material()
        m.elements[0].body.uv_animation = [1]
        cases.append(m)
        m = self.material()
        m.elements[0].body.uv_source = 1
        cases.append(m)
        m = self.material()
        m.elements[0].body.subtype = "RFLD"
        cases.append(m)
        m = self.material()
        m.vertex_attribute_flags = 0xFFFF
        cases.append(m)
        m = self.material()
        m.elements[2].body.value = 0
        cases.append(m)
        for case in cases:
            with self.subTest(case=case), pytest.raises(ValueError, match="Unsupported|Animated|Unknown"):
                checked_material(case, self.templates(), [100, 101], Game.PRIME, 0)

    def test_invalid_target_rejected(self):
        with pytest.raises(ValueError, match="Target must"):
            convert_mesh(None, None, Game.CORRUPTION, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)

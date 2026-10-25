"""Keep inherited CDV/OPR file-provider calls working with RDS 0.44."""
from __future__ import annotations

import functools
import inspect
from pathlib import Path


def _install_legacy_raw_resource_api():
    from retro_data_structures.base_resource import RawResource

    original = RawResource.__init__
    if getattr(original, "_nullphaaze_legacy_data", False):
        return
    parameters = inspect.signature(original).parameters
    if "data" in parameters:
        return
    if "raw_data" not in parameters:
        raise RuntimeError("Unsupported RDS RawResource constructor")

    @functools.wraps(original)
    def initialize(self, *args, **kwargs):
        # OPR 0.15 names the payload data; RDS 0.44 names the stored bytes
        # raw_data and exposes data as its decompressed read-only property.
        if "data" in kwargs:
            if "raw_data" in kwargs:
                raise TypeError("Supply either data or raw_data, not both")
            kwargs["raw_data"] = kwargs.pop("data")
        original(self, *args, **kwargs)

    initialize._nullphaaze_legacy_data = True
    RawResource.__init__ = initialize


def install_legacy_asset_manager_api():
    _install_legacy_raw_resource_api()
    from retro_data_structures.formats.strg import Strg

    if not hasattr(Strg, "set_string"):
        Strg.set_string = Strg.set_single_string
    if not hasattr(Strg, "languages"):
        Strg.languages = property(Strg.get_language_list)
    if not hasattr(Strg, "set_strings"):
        def set_strings(self, language, strings):
            self.set_string_list(list(strings), language=language)

        Strg.set_strings = set_strings
    from retro_data_structures.formats.script_object import ScriptInstance, resolve_instance_id

    if not hasattr(ScriptInstance, "type"):
        ScriptInstance.type = ScriptInstance.script_type
    if not hasattr(ScriptInstance, "remove_connections_from"):
        ScriptInstance.remove_connections_from = ScriptInstance.remove_all_connections_to
    if not hasattr(ScriptInstance, "id_matches"):
        def id_matches(self, other):
            return self.id.matches(resolve_instance_id(other))

        ScriptInstance.id_matches = id_matches
    from retro_data_structures import asset_manager

    if not hasattr(asset_manager.AssetManager, "_resolve_asset_id"):
        asset_manager.AssetManager._resolve_asset_id = asset_manager.AssetManager.resolve_asset_id
    if not hasattr(asset_manager, "PathFileWriter") or hasattr(asset_manager, "PathFileProvider"):
        return
    from retro_data_structures import file_provider
    from retro_data_structures.enums import echoes
    from retro_data_structures.properties.echoes.archetypes.VisorParameters import VisorFlags
    from retro_data_structures.properties.echoes.archetypes.WeaponVulnerability import Effect

    if not hasattr(echoes, "VisorFlags"):
        echoes.VisorFlags = VisorFlags
    if not hasattr(echoes, "Effect"):
        echoes.Effect = Effect
    if not hasattr(echoes, "ScanSpeed"):
        echoes.ScanSpeed = echoes.ScanSpeedEnum

    for name in ("FileProvider", "PathFileProvider", "IsoFileProvider"):
        setattr(asset_manager, name, getattr(file_provider, name))
    original_add = asset_manager.AssetManager.add_new_asset

    @functools.wraps(original_add)
    def add_new_asset(self, name, new_data, paks=()):
        # OPR 0.15 supplied destination PAKs as the third argument. RDS 0.44
        # split that operation into add_new_asset and ensure_present.
        destinations = tuple(paks)
        # Legacy callers reuse and mutate parsed templates after each add.
        # RDS 0.44 retains parsed objects until save; snapshot here so distinct
        # door models, scan strings and similar assets keep their own payloads.
        from retro_data_structures.base_resource import BaseResource, RawResource

        if isinstance(new_data, BaseResource):
            new_data = RawResource(new_data.resource_type(), new_data.build())
        identity = original_add(self, name, new_data)
        for pak in destinations:
            self.ensure_present(pak, identity)
        return identity

    asset_manager.AssetManager.add_new_asset = add_new_asset
    original = asset_manager.AssetManager.save_modifications

    @functools.wraps(original)
    def save_modifications(self, output, pak_status_update=None):
        # RDS 0.44 declares _dol/_tweaks defaults but its writer accesses the
        # public names, which are only assigned for particular target games.
        for name in ("dol", "tweaks"):
            if not hasattr(self, name):
                setattr(self, name, getattr(self, "_" + name, None))
        if isinstance(output, Path):
            # Both inherited callers pass the extracted disc's files folder.
            # RDS 0.44's writer instead takes the extracted disc root.
            if output.name != "files":
                raise ValueError("Legacy asset output must be the extracted disc's files directory")
            output = asset_manager.PathFileWriter(output.parent)
        return original(self, output, pak_status_update)

    asset_manager.AssetManager.save_modifications = save_modifications

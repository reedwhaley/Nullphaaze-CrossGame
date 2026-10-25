from pathlib import Path
import os
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
host = os.environ.get("NULLPHAAZE_CROSSGAME_HOST")
if host:
    sys.path.insert(0, str(ROOT / "scripts"))
    from _host import use_host
    use_host(host, os.environ.get("NULLPHAAZE_MULTIWORLD_SOURCE"), os.environ.get("NULLPHAAZE_CORE_SOURCE"))
else:
    def pytest_ignore_collect(collection_path, config):
        return Path(collection_path).name.startswith("test_")

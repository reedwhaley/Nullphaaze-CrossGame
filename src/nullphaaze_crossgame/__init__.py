"""GPL cross-game conversion primitives; no desktop application or retail assets."""
import json
from importlib.resources import files

__version__ = "0.1.0"

def catalog(name="imported_model_catalog"):
    if name not in {"imported_model_catalog", "corruption_gc_catalog"}:
        raise ValueError("Unknown cross-game catalog")
    return json.loads((files(__package__) / "data" / (name + ".json")).read_text())

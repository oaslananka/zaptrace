"""Library agent tool implementations."""

from __future__ import annotations

from .deps import Any
from .runtime import _get_library, _get_session


def tool_library_search(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the component library by keyword."""
    lib = _get_library()
    results = lib.search(query, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "manufacturer": r.manufacturer,
                "mpn": r.mpn,
                "description": r.description,
                "package": r.package,
                "confidence_score": r.confidence_score,
                "confidence_grade": r.confidence_grade,
            }
            for r in results
        ],
    }


def tool_library_get(component_id: str) -> dict[str, Any]:
    """Get full details for a specific library component."""
    lib = _get_library()
    spec = lib.get(component_id)
    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "manufacturer": spec.manufacturer,
        "mpn": spec.mpn,
        "description": spec.description,
        "datasheet": spec.datasheet,
        "package": spec.package,
        "footprint": spec.footprint,
        "lifecycle": spec.lifecycle,
        "voltage_supply": spec.voltage_supply,
        "pins": spec.pins,
        "properties": spec.properties,
        "confidence_score": spec.confidence_score,
        "confidence_grade": spec.confidence_grade,
        "missing_metadata": spec.missing_metadata,
    }


def tool_library_list_categories() -> dict[str, Any]:
    """List all component library categories."""
    lib = _get_library()
    return {"categories": lib.list_categories()}


def tool_footprint_search(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search for footprints in the library by keyword."""
    library = _get_library()
    results = library.search(query, max_results=max_results)
    footprints = []
    for r in results:
        fp = r.footprint or r.package
        footprints.append(
            {
                "id": r.id,
                "name": r.name,
                "type": r.category,
                "footprint": fp,
                "description": r.description,
            }
        )
    return {"query": query, "count": len(footprints), "footprints": footprints}


def tool_footprint_get(component_id: str) -> dict[str, Any]:
    """Get footprint details for a library component."""
    library = _get_library()
    try:
        comp = library.get(component_id)
    except Exception as e:
        return {"component_id": component_id, "error": str(e)}
    return {
        "component_id": component_id,
        "footprint": comp.footprint,
        "package": comp.package,
        "manufacturer": comp.manufacturer,
        "datasheet": comp.datasheet,
    }


def tool_schematic_render(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Render a design as an SVG schematic using the SchematicEngine."""
    from zaptrace.ee.schematic import SchematicEngine

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    engine = SchematicEngine()
    svg = engine.render(design)
    return {"svg": svg, "design": design_name}


def tool_footprint_generate(package: str, layer: str = "top") -> dict[str, Any]:
    """Generate a parametric footprint for a given package name."""
    from zaptrace.core.models import LayerSet
    from zaptrace.ee.footprints import generate_footprint

    layer_enum = LayerSet.BOTTOM if layer.lower() == "bottom" else LayerSet.TOP
    fp = generate_footprint(package, layer=layer_enum)
    if fp is None:
        return {"package": package, "error": f"Unknown package: {package}"}
    return {
        "package": package,
        "pads": [p.model_dump() for p in fp.pads],
        "outline_commands": [c.model_dump() for c in fp.outline],
        "courtyard_w": fp.courtyard[0],
        "courtyard_h": fp.courtyard[1],
        "description": fp.description,
    }


def tool_footprint_list_packages() -> dict[str, Any]:
    """List all supported package names for footprint generation."""
    from zaptrace.ee.footprints import list_supported_packages

    return {"packages": list_supported_packages(), "count": len(list_supported_packages())}


__all__ = [
    "tool_library_search",
    "tool_library_get",
    "tool_library_list_categories",
    "tool_footprint_search",
    "tool_footprint_get",
    "tool_schematic_render",
    "tool_footprint_generate",
    "tool_footprint_list_packages",
]

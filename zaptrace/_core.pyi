def place_components(
    n: int,
    width_mm: float,
    height_mm: float,
    connections: list[tuple[int, int]],
    min_spacing_mm: float,
) -> list[tuple[float, float]]: ...
def route_mst(points: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]: ...

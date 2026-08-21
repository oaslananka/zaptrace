//! Pure, resource-bounded placement kernel.

use crate::errors::{NativeError, NativeResult};
use crate::limits::{MAX_COMPONENTS, MAX_PLACEMENT_CONNECTIONS};
use crate::validation::{bounded_len, non_negative, positive};

pub(crate) fn place_components(
    n: usize,
    width_mm: f64,
    height_mm: f64,
    connections: &[(usize, usize)],
    min_spacing_mm: f64,
) -> NativeResult<Vec<(f64, f64)>> {
    bounded_len("components", n, MAX_COMPONENTS)?;
    bounded_len(
        "placement_connections",
        connections.len(),
        MAX_PLACEMENT_CONNECTIONS,
    )?;
    let width_mm = positive("width_mm", width_mm)?;
    let height_mm = positive("height_mm", height_mm)?;
    let min_spacing_mm = non_negative("min_spacing_mm", min_spacing_mm)?;

    for &(a, b) in connections {
        if a >= n || b >= n {
            return Err(NativeError::IndexOutOfBounds { a, b, n });
        }
    }

    let margin = min_spacing_mm.max(5.0);
    if width_mm <= 2.0 * margin {
        return Err(NativeError::InvalidRange {
            field: "width_mm",
            message: "must be greater than twice the effective margin",
        });
    }
    if height_mm <= 2.0 * margin {
        return Err(NativeError::InvalidRange {
            field: "height_mm",
            message: "must be greater than twice the effective margin",
        });
    }
    if n == 0 {
        return Ok(Vec::new());
    }

    let grid_cols = ((n as f64 * width_mm / height_mm).sqrt().ceil() as usize).max(1);
    let grid_rows = (n as f64 / grid_cols as f64).ceil() as usize;
    let cell_w = (width_mm - 2.0 * margin) / grid_cols as f64;
    let cell_h = (height_mm - 2.0 * margin) / grid_rows as f64;

    let mut positions: Vec<(f64, f64)> = (0..n)
        .map(|idx| {
            let col = idx % grid_cols;
            let row = idx / grid_cols;
            (
                margin + col as f64 * cell_w + cell_w / 2.0,
                margin + row as f64 * cell_h + cell_h / 2.0,
            )
        })
        .collect();

    let rest_length = 8.0;
    let spring_k = 0.05;
    let repulsion_strength = 2.0;
    let repulsion_radius = 10.0;

    for _ in 0..20 {
        let mut forces: Vec<(f64, f64)> = vec![(0.0, 0.0); n];

        for &(a, b) in connections {
            let (ax, ay) = positions[a];
            let (bx, by) = positions[b];
            let dx = bx - ax;
            let dy = by - ay;
            let distance = (dx * dx + dy * dy).sqrt().max(0.1);
            let stretch = distance - rest_length;
            let unit_x = dx / distance;
            let unit_y = dy / distance;
            let force_x = spring_k * stretch * unit_x;
            let force_y = spring_k * stretch * unit_y;
            forces[a].0 += force_x;
            forces[a].1 += force_y;
            forces[b].0 -= force_x;
            forces[b].1 -= force_y;
        }

        for i in 0..n {
            for j in (i + 1)..n {
                let (ax, ay) = positions[i];
                let (bx, by) = positions[j];
                let dx = bx - ax;
                let dy = by - ay;
                let dist = (dx * dx + dy * dy).sqrt().max(0.1);
                if dist < repulsion_radius {
                    let rep = repulsion_strength / (dist * dist);
                    let fx = -rep * dx / dist;
                    let fy = -rep * dy / dist;
                    forces[i].0 += fx;
                    forces[i].1 += fy;
                    forces[j].0 -= fx;
                    forces[j].1 -= fy;
                }
            }
        }

        for i in 0..n {
            let (x, y) = positions[i];
            let new_x = (x + forces[i].0).clamp(margin, width_mm - margin);
            let new_y = (y + forces[i].1).clamp(margin, height_mm - margin);
            positions[i] = (new_x, new_y);
        }
    }

    Ok(positions)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placement_is_deterministic_and_bounded() {
        let connections = [(0, 1), (1, 2)];
        let first = place_components(3, 100.0, 80.0, &connections, 5.0).unwrap();
        let second = place_components(3, 100.0, 80.0, &connections, 5.0).unwrap();
        assert_eq!(first, second);
        assert!(first.iter().all(|(x, y)| {
            x.is_finite() && y.is_finite() && *x >= 5.0 && *x <= 95.0 && *y >= 5.0 && *y <= 75.0
        }));
    }

    #[test]
    fn placement_rejects_invalid_indices_and_geometry() {
        assert!(matches!(
            place_components(2, 100.0, 80.0, &[(0, 2)], 5.0),
            Err(NativeError::IndexOutOfBounds { a: 0, b: 2, n: 2 })
        ));
        assert!(matches!(
            place_components(1, f64::NAN, 80.0, &[], 5.0),
            Err(NativeError::NonFinite { field: "width_mm" })
        ));
        assert!(matches!(
            place_components(1, 10.0, 80.0, &[], 5.0),
            Err(NativeError::InvalidRange {
                field: "width_mm",
                ..
            })
        ));
        assert!(matches!(
            place_components(1, 100.0, 80.0, &[], -0.1),
            Err(NativeError::InvalidRange {
                field: "min_spacing_mm",
                ..
            })
        ));
    }

    #[test]
    fn placement_enforces_resource_limits() {
        assert!(matches!(
            place_components(MAX_COMPONENTS + 1, 100.0, 80.0, &[], 5.0),
            Err(NativeError::ResourceLimit {
                resource: "components",
                ..
            })
        ));
        let connections = vec![(0, 0); MAX_PLACEMENT_CONNECTIONS + 1];
        assert!(matches!(
            place_components(1, 100.0, 80.0, &connections, 5.0),
            Err(NativeError::ResourceLimit {
                resource: "placement_connections",
                ..
            })
        ));
    }

    #[test]
    fn empty_placement_remains_supported_for_valid_geometry() {
        assert_eq!(place_components(0, 100.0, 80.0, &[], 5.0).unwrap(), vec![]);
    }
}

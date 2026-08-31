//! Pure, resource-bounded routing kernels.

use crate::errors::NativeResult;
use crate::limits::{MAX_MST_POINTS, MAX_SHOVE_CONNECTIONS, MAX_SHOVE_OBSTACLES};
use crate::validation::{bounded_len, finite, non_negative, validate_points, validate_segments};

pub(crate) type Segment = (f64, f64, f64, f64);
pub(crate) type ShoveConnection = (f64, f64, f64, f64, String);

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ShoveResult {
    pub(crate) net_id: String,
    pub(crate) provenance: String,
    pub(crate) resolved: bool,
    pub(crate) segments: Vec<Segment>,
}

pub(crate) fn route_mst(points: &[(f64, f64)]) -> NativeResult<Vec<Segment>> {
    bounded_len("mst_points", points.len(), MAX_MST_POINTS)?;
    validate_points(points)?;
    let n = points.len();
    if n < 2 {
        return Ok(Vec::new());
    }

    let mut in_mst = vec![false; n];
    in_mst[0] = true;
    let mut edges: Vec<(usize, usize)> = Vec::with_capacity(n - 1);

    for _ in 0..(n - 1) {
        let Some(mut best_i) = in_mst.iter().position(|included| *included) else {
            break;
        };
        let Some(mut best_j) = in_mst.iter().position(|included| !*included) else {
            break;
        };
        let mut best_dist =
            (points[best_i].0 - points[best_j].0).hypot(points[best_i].1 - points[best_j].1);

        for i in 0..n {
            if !in_mst[i] {
                continue;
            }
            for j in 0..n {
                if in_mst[j] {
                    continue;
                }
                let dx = points[i].0 - points[j].0;
                let dy = points[i].1 - points[j].1;
                let dist = dx.hypot(dy);
                if dist < best_dist {
                    best_dist = dist;
                    best_i = i;
                    best_j = j;
                }
            }
        }

        edges.push((best_i, best_j));
        in_mst[best_j] = true;
    }

    let mut segments: Vec<Segment> = Vec::with_capacity(edges.len() * 2);
    for &(i, j) in &edges {
        let (x1, y1) = points[i];
        let (x2, y2) = points[j];
        segments.push((x1, y1, x2, y1));
        segments.push((x2, y1, x2, y2));
    }
    Ok(segments)
}

fn aabb_overlap(a: Segment, b: Segment) -> bool {
    let (ax1, ay1, ax2, ay2) = a;
    let (bx1, by1, bx2, by2) = b;
    ax1.min(ax2) < bx1.max(bx2)
        && ax1.max(ax2) > bx1.min(bx2)
        && ay1.min(ay2) < by1.max(by2)
        && ay1.max(ay2) > by1.min(by2)
}

fn try_shove_walkaround(
    start: (f64, f64),
    end: (f64, f64),
    obstacles: &[Segment],
    clearance: f64,
) -> NativeResult<ShoveResult> {
    let (x1, y1) = start;
    let (x2, y2) = end;
    let naive = vec![(x1, y1, x2, y1), (x2, y1, x2, y2)];
    let naive_blocked = obstacles.iter().any(|&obstacle| {
        aabb_overlap((x1, y1, x2, y1), obstacle) || aabb_overlap((x2, y1, x2, y2), obstacle)
    });

    if !naive_blocked {
        return Ok(ShoveResult {
            net_id: String::new(),
            segments: naive,
            provenance: "direct-l-path".into(),
            resolved: true,
        });
    }

    let detour_y = obstacles
        .iter()
        .map(|&(_, _, _, oy2)| oy2 + clearance)
        .fold(f64::NEG_INFINITY, f64::max)
        .max(y1.max(y2) + clearance);
    let detour_y = finite("detour_y", detour_y)?;
    let walkaround = vec![
        (x1, y1, x1, detour_y),
        (x1, detour_y, x2, detour_y),
        (x2, detour_y, x2, y2),
    ];
    let walkaround_blocked = obstacles.iter().any(|&obstacle| {
        walkaround
            .iter()
            .any(|&segment| aabb_overlap(segment, obstacle))
    });

    if !walkaround_blocked {
        return Ok(ShoveResult {
            net_id: String::new(),
            segments: walkaround,
            provenance: format!("walkaround-above-y{detour_y:.3}"),
            resolved: true,
        });
    }

    Ok(ShoveResult {
        net_id: String::new(),
        segments: naive,
        provenance: "no-solution-naive-fallback".into(),
        resolved: false,
    })
}

pub(crate) fn route_shove(
    connections: Vec<ShoveConnection>,
    obstacles: &[Segment],
    clearance: f64,
) -> NativeResult<Vec<ShoveResult>> {
    bounded_len(
        "shove_connections",
        connections.len(),
        MAX_SHOVE_CONNECTIONS,
    )?;
    bounded_len("shove_obstacles", obstacles.len(), MAX_SHOVE_OBSTACLES)?;
    let clearance = non_negative("clearance", clearance)?;
    validate_segments(obstacles)?;
    let connection_segments: Vec<Segment> = connections
        .iter()
        .map(|&(x1, y1, x2, y2, _)| (x1, y1, x2, y2))
        .collect();
    validate_segments(&connection_segments)?;

    let mut results = Vec::with_capacity(connections.len());
    for (x1, y1, x2, y2, net_id) in connections {
        let mut outcome = try_shove_walkaround((x1, y1), (x2, y2), obstacles, clearance)?;
        outcome.net_id = net_id;
        results.push(outcome);
    }
    Ok(results)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::errors::NativeError;

    #[test]
    fn mst_is_deterministic_and_has_expected_segments() {
        let points = [(0.0, 0.0), (100.0, 0.0), (50.0, 100.0)];
        let first = route_mst(&points).unwrap();
        let second = route_mst(&points).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.len(), 4);
        assert!(first.iter().all(|segment| {
            let (x1, y1, x2, y2) = *segment;
            [x1, y1, x2, y2].into_iter().all(f64::is_finite)
        }));
    }

    #[test]
    fn mst_rejects_non_finite_and_excessive_input() {
        assert!(matches!(
            route_mst(&[(0.0, f64::INFINITY)]),
            Err(NativeError::NonFinite { field: "point.y" })
        ));
        let points = vec![(0.0, 0.0); MAX_MST_POINTS + 1];
        assert!(matches!(
            route_mst(&points),
            Err(NativeError::ResourceLimit {
                resource: "mst_points",
                ..
            })
        ));
    }

    #[test]
    fn mst_progresses_with_extreme_finite_coordinates() {
        let points = [(1e308, 0.0), (-1e308, 0.0), (0.0, 1.0)];
        let segments = route_mst(&points).unwrap();
        let reached: Vec<(f64, f64)> = segments
            .as_chunks::<2>()
            .0
            .iter()
            .map(|edge| (edge[1].2, edge[1].3))
            .collect();

        assert_eq!(reached.len(), points.len() - 1);
        assert!(reached.contains(&(0.0, 1.0)));
    }

    #[test]
    fn mst_empty_and_single_point_remain_supported() {
        assert_eq!(route_mst(&[]).unwrap(), vec![]);
        assert_eq!(route_mst(&[(1.0, 2.0)]).unwrap(), vec![]);
    }

    #[test]
    fn shove_is_deterministic_and_finite() {
        let connections = vec![(0.0, 5.0, 20.0, 5.0, "N1".to_string())];
        let obstacles = [(8.0, 2.0, 12.0, 8.0)];
        let first = route_shove(connections.clone(), &obstacles, 0.2).unwrap();
        let second = route_shove(connections, &obstacles, 0.2).unwrap();
        assert_eq!(first, second);
        assert_eq!(first[0].net_id, "N1");
        assert!(first[0].segments.iter().all(|segment| {
            let (x1, y1, x2, y2) = *segment;
            [x1, y1, x2, y2].into_iter().all(f64::is_finite)
        }));
    }

    #[test]
    fn shove_rejects_overflow_from_extreme_finite_input() {
        let connections = vec![(0.0, 0.0, 30.0, 10.0, "N".to_string())];
        let obstacles = [(10.0, -1.0, 20.0, 1e308)];

        assert!(matches!(
            route_shove(connections, &obstacles, 1e308),
            Err(NativeError::NonFinite { field: "detour_y" })
        ));
    }

    #[test]
    fn shove_rejects_invalid_and_excessive_input() {
        assert!(matches!(
            route_shove(vec![], &[], f64::NAN),
            Err(NativeError::NonFinite { field: "clearance" })
        ));
        assert!(matches!(
            route_shove(vec![], &[], -0.1),
            Err(NativeError::InvalidRange {
                field: "clearance",
                ..
            })
        ));
        let connections = vec![(0.0, 0.0, 1.0, 1.0, "N".to_string()); MAX_SHOVE_CONNECTIONS + 1];
        assert!(matches!(
            route_shove(connections, &[], 0.2),
            Err(NativeError::ResourceLimit {
                resource: "shove_connections",
                ..
            })
        ));
        let obstacles = vec![(0.0, 0.0, 1.0, 1.0); MAX_SHOVE_OBSTACLES + 1];
        assert!(matches!(
            route_shove(vec![], &obstacles, 0.2),
            Err(NativeError::ResourceLimit {
                resource: "shove_obstacles",
                ..
            })
        ));
        assert!(matches!(
            route_shove(vec![(0.0, 0.0, f64::NAN, 1.0, "N".to_string())], &[], 0.2,),
            Err(NativeError::NonFinite {
                field: "segment.x2"
            })
        ));
    }
}

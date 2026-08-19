//! Validation helpers shared by native kernels.

use crate::errors::{NativeError, NativeResult};

pub(crate) fn finite(field: &'static str, value: f64) -> NativeResult<f64> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(NativeError::NonFinite { field })
    }
}

pub(crate) fn non_negative(field: &'static str, value: f64) -> NativeResult<f64> {
    let value = finite(field, value)?;
    if value >= 0.0 {
        Ok(value)
    } else {
        Err(NativeError::InvalidRange {
            field,
            message: "must be non-negative",
        })
    }
}

pub(crate) fn positive(field: &'static str, value: f64) -> NativeResult<f64> {
    let value = finite(field, value)?;
    if value > 0.0 {
        Ok(value)
    } else {
        Err(NativeError::InvalidRange {
            field,
            message: "must be positive",
        })
    }
}

pub(crate) fn bounded_len(
    resource: &'static str,
    actual: usize,
    maximum: usize,
) -> NativeResult<()> {
    if actual <= maximum {
        Ok(())
    } else {
        Err(NativeError::ResourceLimit {
            resource,
            actual,
            maximum,
        })
    }
}

pub(crate) fn validate_points(points: &[(f64, f64)]) -> NativeResult<()> {
    for &(x, y) in points {
        finite("point.x", x)?;
        finite("point.y", y)?;
    }
    Ok(())
}

pub(crate) fn validate_segments(segments: &[(f64, f64, f64, f64)]) -> NativeResult<()> {
    for &(x1, y1, x2, y2) in segments {
        finite("segment.x1", x1)?;
        finite("segment.y1", y1)?;
        finite("segment.x2", x2)?;
        finite("segment.y2", y2)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::errors::NativeError;
    use crate::limits::{
        MAX_COMPONENTS, MAX_MST_POINTS, MAX_PLACEMENT_CONNECTIONS, MAX_SHOVE_CONNECTIONS,
        MAX_SHOVE_OBSTACLES,
    };

    #[test]
    fn rejects_non_finite_values() {
        assert!(matches!(
            finite("width_mm", f64::NAN),
            Err(NativeError::NonFinite { field: "width_mm" })
        ));
        assert!(matches!(
            finite("height_mm", f64::INFINITY),
            Err(NativeError::NonFinite { field: "height_mm" })
        ));
    }

    #[test]
    fn accepts_finite_and_non_negative_values() {
        assert_eq!(finite("width_mm", 100.0).unwrap(), 100.0);
        assert_eq!(non_negative("clearance", 0.0).unwrap(), 0.0);
        assert_eq!(positive("height_mm", 80.0).unwrap(), 80.0);
    }

    #[test]
    fn rejects_negative_or_zero_ranges() {
        assert!(matches!(
            non_negative("clearance", -0.1),
            Err(NativeError::InvalidRange {
                field: "clearance",
                ..
            })
        ));
        assert!(matches!(
            positive("width_mm", 0.0),
            Err(NativeError::InvalidRange {
                field: "width_mm",
                ..
            })
        ));
    }

    #[test]
    fn rejects_resource_limit_overflow() {
        assert!(bounded_len("components", MAX_COMPONENTS, MAX_COMPONENTS).is_ok());
        assert!(matches!(
            bounded_len("components", MAX_COMPONENTS + 1, MAX_COMPONENTS),
            Err(NativeError::ResourceLimit {
                resource: "components",
                actual,
                maximum: MAX_COMPONENTS,
            }) if actual == MAX_COMPONENTS + 1
        ));
        assert!(bounded_len("mst_points", MAX_MST_POINTS, MAX_MST_POINTS).is_ok());
        assert!(bounded_len(
            "placement_connections",
            MAX_PLACEMENT_CONNECTIONS,
            MAX_PLACEMENT_CONNECTIONS,
        )
        .is_ok());
        assert!(bounded_len(
            "shove_connections",
            MAX_SHOVE_CONNECTIONS,
            MAX_SHOVE_CONNECTIONS,
        )
        .is_ok());
        assert!(bounded_len("shove_obstacles", MAX_SHOVE_OBSTACLES, MAX_SHOVE_OBSTACLES,).is_ok());
    }

    #[test]
    fn index_error_has_stable_message() {
        let error = NativeError::IndexOutOfBounds { a: 1, b: 3, n: 2 };
        assert_eq!(
            error.to_string(),
            "connection index out of bounds: (1, 3) for n=2"
        );
    }

    #[test]
    fn rejects_non_finite_coordinate_tuples() {
        assert!(validate_points(&[(0.0, 1.0), (2.0, 3.0)]).is_ok());
        assert!(matches!(
            validate_points(&[(0.0, f64::NEG_INFINITY)]),
            Err(NativeError::NonFinite { field: "point.y" })
        ));
        assert!(matches!(
            validate_segments(&[(0.0, 1.0, f64::NAN, 3.0)]),
            Err(NativeError::NonFinite {
                field: "segment.x2"
            })
        ));
    }
}

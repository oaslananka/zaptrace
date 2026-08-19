//! ZapTrace Core — accelerated, resource-bounded placement and routing routines.

use std::panic::{catch_unwind, AssertUnwindSafe};

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyList;

mod errors;
mod limits;
mod placement;
mod routing;
mod validation;

use errors::NativeError;
use limits::{
    MAX_MST_POINTS, MAX_PLACEMENT_CONNECTIONS, MAX_SHOVE_CONNECTIONS, MAX_SHOVE_OBSTACLES,
};

type PyShoveResult = (String, String, bool, Vec<(f64, f64, f64, f64)>);

fn native_value_error(error: NativeError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

#[derive(Debug, PartialEq, Eq)]
enum BoundaryFailure {
    Native(NativeError),
    Panic,
}

fn catch_boundary<T, F>(operation: F) -> Result<T, BoundaryFailure>
where
    F: FnOnce() -> Result<T, NativeError>,
{
    match catch_unwind(AssertUnwindSafe(operation)) {
        Ok(result) => result.map_err(BoundaryFailure::Native),
        Err(_) => Err(BoundaryFailure::Panic),
    }
}

fn boundary_call<T, F>(operation: F) -> PyResult<T>
where
    F: FnOnce() -> Result<T, NativeError>,
{
    catch_boundary(operation).map_err(|failure| match failure {
        BoundaryFailure::Native(error) => native_value_error(error),
        BoundaryFailure::Panic => PyRuntimeError::new_err("native operation failed unexpectedly"),
    })
}

fn preflight_sequence(
    value: &Bound<'_, PyList>,
    resource: &'static str,
    maximum: usize,
) -> PyResult<()> {
    validation::bounded_len(resource, value.len(), maximum).map_err(native_value_error)
}

/// Place components on a board using the bounded native placement kernel.
#[pyfunction]
fn place_components(
    n: usize,
    width_mm: f64,
    height_mm: f64,
    connections: &Bound<'_, PyList>,
    min_spacing_mm: f64,
) -> PyResult<Vec<(f64, f64)>> {
    preflight_sequence(
        connections,
        "placement_connections",
        MAX_PLACEMENT_CONNECTIONS,
    )?;
    let connections = connections.extract::<Vec<(usize, usize)>>()?;
    boundary_call(|| {
        placement::place_components(n, width_mm, height_mm, &connections, min_spacing_mm)
    })
}

/// Route points using a deterministic Manhattan minimum spanning tree.
#[pyfunction]
fn route_mst(points: &Bound<'_, PyList>) -> PyResult<Vec<(f64, f64, f64, f64)>> {
    preflight_sequence(points, "mst_points", MAX_MST_POINTS)?;
    let points = points.extract::<Vec<(f64, f64)>>()?;
    boundary_call(|| routing::route_mst(&points))
}

/// Route connections through the bounded deterministic shove kernel.
#[pyfunction]
fn route_shove(
    connections: &Bound<'_, PyList>,
    obstacles: &Bound<'_, PyList>,
    clearance: f64,
) -> PyResult<Vec<PyShoveResult>> {
    preflight_sequence(connections, "shove_connections", MAX_SHOVE_CONNECTIONS)?;
    preflight_sequence(obstacles, "shove_obstacles", MAX_SHOVE_OBSTACLES)?;
    let connections = connections.extract::<Vec<(f64, f64, f64, f64, String)>>()?;
    let obstacles = obstacles.extract::<Vec<(f64, f64, f64, f64)>>()?;
    boundary_call(|| routing::route_shove(connections, &obstacles, clearance)).map(|results| {
        results
            .into_iter()
            .map(|result| {
                (
                    result.net_id,
                    result.provenance,
                    result.resolved,
                    result.segments,
                )
            })
            .collect()
    })
}

#[pymodule]
fn _core(_py: Python, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(place_components, module)?)?;
    module.add_function(wrap_pyfunction!(route_mst, module)?)?;
    module.add_function(wrap_pyfunction!(route_shove, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundary_guard_converts_panics() {
        let result = catch_boundary::<(), _>(|| panic!("deliberate boundary test"));
        assert_eq!(result, Err(BoundaryFailure::Panic));
    }
}

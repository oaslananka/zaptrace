//! Typed native validation and boundary errors.

use std::fmt;

/// Error returned by a pure native kernel before conversion to a Python exception.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum NativeError {
    NonFinite {
        field: &'static str,
    },
    InvalidRange {
        field: &'static str,
        message: &'static str,
    },
    IndexOutOfBounds {
        a: usize,
        b: usize,
        n: usize,
    },
    ResourceLimit {
        resource: &'static str,
        actual: usize,
        maximum: usize,
    },
}

pub(crate) type NativeResult<T> = Result<T, NativeError>;

impl fmt::Display for NativeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NonFinite { field } => write!(formatter, "{field} must be finite"),
            Self::InvalidRange { field, message } => write!(formatter, "{field} {message}"),
            Self::IndexOutOfBounds { a, b, n } => {
                write!(
                    formatter,
                    "connection index out of bounds: ({a}, {b}) for n={n}"
                )
            }
            Self::ResourceLimit {
                resource,
                actual,
                maximum,
            } => write!(
                formatter,
                "{resource} count {actual} exceeds supported maximum {maximum}"
            ),
        }
    }
}

impl std::error::Error for NativeError {}

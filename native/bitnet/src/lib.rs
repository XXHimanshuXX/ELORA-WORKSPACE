//! elora_bitnet — addition-only b1.58 kernels.
//! Weights in {-1, 0, 1}. No multiply of weights. pyo3 binding.

use pyo3::prelude::*;

/// y = x @ W  for ternary W. Addition / subtraction only.
#[pyfunction]
fn ternary_matmul(x: Vec<f32>, weights: Vec<i8>, n_out: usize) -> PyResult<Vec<f32>> {
    let n_in = x.len();
    if n_in == 0 || n_out == 0 || n_in * n_out != weights.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("shape mismatch"));
    }
    let mut y = vec![0f32; n_out];
    for j in 0..n_out {
        let mut acc = 0f32;
        let row = j * n_in;
        for i in 0..n_in {
            match weights[row + i] {
                1 => acc += x[i],
                -1 => acc -= x[i],
                _ => {}
            }
        }
        y[j] = acc;
    }
    Ok(y)
}

#[pymodule]
fn elora_bitnet(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ternary_matmul, m)?)?;
    m.add("AWAKE_RSS_MB", 380)?;
    Ok(())
}

# SI/PI/thermal heuristic reports

ZapTrace provides transparent, non-signoff engineering reports for early design review. The reports are machine-readable JSON plus Markdown and can be attached to proof-pack artifacts.

Implemented API:

- `generate_electrical_analysis_report(design)`
- `render_analysis_markdown(report)`
- `build_analysis_proof_artifacts(report, output_dir)`

Coverage:

- controlled-impedance target versus heuristic microstrip width/gap estimate;
- differential-pair and length-match group checks from `Net.constraints`;
- max-length checks from `Net.constraints.max_length_mm`;
- coarse PDN IR-drop/current-density estimate using routed length, trace width, and component `current_a` metadata;
- coarse thermal hotspot estimate using component `power_w` and `theta_ja_c_per_w` metadata.

Limitations:

- These reports are heuristic and nonblocking by default.
- They do not replace field solvers, SPICE/PDN simulation, or CFD/thermal simulation.
- Production signoff still requires external tool validation and human review.

from __future__ import annotations

import json

from zaptrace.benchmark.mutations import (
    BUILTIN_MUTATIONS,
    MutationClass,
    _narrow_high_current_trace,
    _remove_decoupling,
    _remove_return_path,
    apply_known_failure_mutation,
    mutation_corpus_json,
    run_known_failure_mutation_corpus,
)
from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetConstraints,
    NetNode,
    NetType,
    RouteResult,
    TraceSegment,
)


def _base_design() -> Design:
    return Design(
        meta=DesignMeta(name="mutation-corpus"),
        components={
            "c1": Component(id="c1", ref="C1", type="capacitor", value="100nF"),
            "u1": Component(id="u1", ref="U1", type="mcu", value="MCU"),
        },
        nets={
            "vdd": Net(
                id="vdd",
                name="VDD_3V3",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="C1", pin_name="1"), NetNode(component_ref="U1", pin_name="VDD")],
            ),
            "motor": Net(
                id="motor",
                name="MOTOR_12V",
                type=NetType.POWER,
                constraints=NetConstraints(is_high_current=True, min_trace_width_mm=0.8),
            ),
            "hs": Net(
                id="hs",
                name="HS_DATA",
                type=NetType.SIGNAL,
                constraints=NetConstraints(impedance_target=50.0, return_path_net="gnd"),
            ),
            "gnd": Net(id="gnd", name="GND", type=NetType.GROUND),
        },
        routing=RouteResult(traces=[TraceSegment(layer="F.Cu", start=(0, 0), end=(10, 0), width=1.0, net_id="motor")]),
    )


def test_builtin_mutation_corpus_has_three_classes() -> None:
    classes = {mutation.mutation_class for mutation in BUILTIN_MUTATIONS}

    assert classes == {
        MutationClass.REMOVE_DECOUPLING,
        MutationClass.NARROW_HIGH_CURRENT_TRACE,
        MutationClass.REMOVE_RETURN_PATH,
    }
    assert all(mutation.release_blocking for mutation in BUILTIN_MUTATIONS)


def test_apply_known_failure_mutation_does_not_mutate_original() -> None:
    design = _base_design()
    mutation = next(
        item for item in BUILTIN_MUTATIONS if item.mutation_class == MutationClass.NARROW_HIGH_CURRENT_TRACE
    )

    mutated = apply_known_failure_mutation(design, mutation)

    assert design.routing is not None
    assert design.routing.traces[0].width == 1.0
    assert mutated.routing is not None
    assert mutated.routing.traces[0].width == 0.05


def test_run_known_failure_mutation_corpus_reports_caught_failures() -> None:
    report = run_known_failure_mutation_corpus(_base_design())

    assert report.mutation_count == 3
    assert report.caught_count == 3
    assert report.missed_count == 0
    assert report.passed is True
    assert {result.expected_detector for result in report.results} == {
        "sipi-risk.decoupling",
        "current-density.violation",
        "sipi-risk.return-path",
    }


def test_mutation_corpus_report_json_shape() -> None:
    report = run_known_failure_mutation_corpus(_base_design())
    data = json.loads(mutation_corpus_json(report))

    assert data["schema_version"] == "1.0"
    assert data["mutation_count"] == 3
    assert data["passed"] is True
    assert len(data["results"]) == 3


def test_mutation_helpers_apply_one_bounded_change() -> None:
    decoupling = _base_design()
    _remove_decoupling(decoupling)
    assert "c1" not in decoupling.components

    current = _base_design()
    _narrow_high_current_trace(current)
    assert current.routing is not None
    assert current.routing.traces[0].width == 0.05

    return_path = _base_design()
    _remove_return_path(return_path)
    assert return_path.nets["hs"].constraints is not None
    assert return_path.nets["hs"].constraints.return_path_net is None

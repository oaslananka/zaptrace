"""CLI commands for Proof Pack management."""

from __future__ import annotations

from pathlib import Path

import click

from zaptrace.cli.output import console, print_summary, print_table
from zaptrace.proof import ProofPack, run_proof, validate_proof_pack

_PROOF_MANIFEST_NAME = "proof.yaml"


@click.group()
def proof() -> None:
    """Manage and run Proof Packs."""


@proof.command()
@click.argument("intent")
@click.option("--output", "-o", type=click.Path(), default="proof-pack", help="Output directory for the bundle")
@click.option("--name", "-n", default="SynthesizedBoard", help="Design name")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]), default="text")
def synth(intent: str, output: str, name: str, output_format: str) -> None:
    """Synthesize a board from INTENT and emit an auditable proof pack.

    Writes design.yaml, proof.yaml, and report.json into the output directory:
    the routed design, every synthesis decision, and the ERC/DRC baselines.
    """
    from zaptrace.synthesis.proof import generate_synthesis_proof

    try:
        pack = generate_synthesis_proof(intent, output, name=name)
        if output_format == "json":
            console.print(pack.report_json())
        else:
            console.print(pack.summary)
            console.print(f"\nBundle written to {output}/ (design.yaml, proof.yaml, report.json)")
        if not pack.passed:
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        print_summary(False, f"Synthesis proof failed: {e}")
        raise click.Abort() from e


def _emit_json_report(pack: ProofPack, output: str | None) -> None:
    report = pack.report_json()
    if output:
        Path(output).write_text(report)
        print_summary(True, f"Proof report written to {output}")
        return
    console.print(report)


def _emit_verbose_results(pack: ProofPack) -> None:
    if not pack.results:
        return

    import json as json_module

    console.print("\n[bold]Details:[/]")
    for result in pack.results:
        status_icon = "✓" if result.passed else "✗"
        status_style = "green" if result.passed else "red"
        console.print(f"  [{status_style}]{status_icon}[/] {result.check.name}: {result.message}")
        if result.details:
            console.print(f"    {json_module.dumps(result.details, indent=4)}")


def _render_proof_run(pack: ProofPack, *, verbose: bool, output_format: str, output: str | None) -> bool:
    if output_format == "json":
        _emit_json_report(pack, output)
        return True

    console.print(pack.summary)
    if verbose:
        _emit_verbose_results(pack)
    return False


@proof.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed check output")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--output", "-o", type=click.Path(), default=None, help="Write report to file")
def run(path: str, verbose: bool, output_format: str, output: str | None) -> None:
    """Run a Proof Pack against a design.

    PATH can be a proof.yaml file or a directory containing proof.yaml.
    """
    try:
        pack = run_proof(path)
        if _render_proof_run(pack, verbose=verbose, output_format=output_format, output=output):
            return
        if not pack.passed:
            raise SystemExit(1)
    except FileNotFoundError as e:
        print_summary(False, str(e))
        raise click.Abort() from e
    except Exception as e:
        print_summary(False, f"Proof pack failed: {e}")
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
def list(path: str) -> None:  # noqa: A001
    """List all checks in a Proof Pack without running them."""
    try:
        path_obj = Path(path)
        if path_obj.is_dir():
            path_obj = path_obj / _PROOF_MANIFEST_NAME
        pack = ProofPack.load(path_obj)

        if not pack.manifest.checks:
            print_summary(False, "No checks defined in proof pack")
            return

        print_table(
            f"Proof Pack: {pack.manifest.name}",
            columns=["Name", "Type", "Severity", "Description"],
            rows=[
                [
                    c.name,
                    c.type,
                    c.severity.value,
                    c.description[:50] if c.description else "",
                ]
                for c in pack.manifest.checks
            ],
        )
    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
def info(path: str) -> None:
    """Show proof pack metadata."""
    try:
        path_obj = Path(path)
        if path_obj.is_dir():
            path_obj = path_obj / _PROOF_MANIFEST_NAME
        pack = ProofPack.load(path_obj)
        m = pack.manifest

        console.print(f"[bold]Name:[/] {m.name}")
        console.print(f"[bold]Version:[/] {m.version}")
        console.print(f"[bold]Description:[/] {m.description or '(none)'}")
        console.print(f"[bold]Design:[/] {m.design_path}")
        console.print(f"[bold]Author:[/] {m.author or '(unknown)'}")
        console.print(f"[bold]Checks:[/] {len(m.checks)}")
        console.print(f"[bold]References:[/] {len(m.references)}")
        console.print(f"[bold]Tags:[/] {', '.join(m.tags) if m.tags else '(none)'}")
        console.print(f"[bold]Requires:[/] {', '.join(m.requires) if m.requires else '(none)'}")

        console.print("\n[bold]Constraints:[/]")
        console.print(f"  Min clearance: {m.model.min_clearance_mm}mm")
        console.print(f"  Min trace width: {m.model.min_trace_width_mm}mm")
        console.print(f"  Min annular ring: {m.model.min_annular_ring_mm}mm")
        console.print(f"  Max layers: {m.model.max_layer_count}")
        console.print(f"  Allowed layers: {m.model.allowed_layer_counts}")

    except Exception as e:
        print_summary(False, str(e))
        raise click.Abort() from e


@proof.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Exit non-zero on warnings, not just errors")
def validate(path: str, strict: bool) -> None:
    """Validate a proof pack manifest and its artifacts.

    PATH can be a proof.yaml file, a .proof.zip bundle, or a directory.

    Checks schema conformance, artifact existence, SHA-256 hashes,
    check record integrity, and the human-review limitation warning.
    """
    try:
        target = Path(path)
        base = Path(".")

        if target.is_dir():
            proof_path = target / _PROOF_MANIFEST_NAME
            if not proof_path.exists():
                print_summary(False, f"No {_PROOF_MANIFEST_NAME} found in {target}")
                raise click.Abort()
            base = target
        else:
            proof_path = target
            base = target.parent

        pack = ProofPack.load(proof_path)
        errors = validate_proof_pack(pack.manifest, base)
        if not errors:
            print_summary(True, "Proof pack is valid.")
            return

        console.print("[red]Validation errors:[/]")
        for e in errors:
            console.print(f"  - {e}")

        n_fail = sum(1 for e in errors if "missing" in e.lower() or "mismatch" in e.lower() or "required" in e.lower())

        if strict:
            raise SystemExit(1)
        if n_fail > 0:
            raise SystemExit(1)

    except click.Abort:
        raise
    except Exception as e:
        print_summary(False, f"Validation failed: {e}")
        raise click.Abort() from e

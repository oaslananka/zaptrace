"""ngspice operating-point runner (optional external tool).

This is a thin, skip-aware adapter around ``ngspice``: if the binary is not on
PATH it returns a ``skipped`` result rather than failing, mirroring how the
KiCad oracle treats a missing ``kicad-cli``. It does not bundle a simulator.

The pure helpers — :func:`with_op_control` (inject a ``.op`` control block) and
:func:`parse_op_output` (read node voltages from ngspice batch output) — are
unit-tested directly so the logic is covered even where ngspice is absent (CI).

Transient analysis is supported via :func:`run_transient`, which runs a ``.tran``
simulation and parses per-timepoint waveform data for startup-time and
steady-state ripple checks.

AC analysis is supported via :func:`run_ac`, which runs a ``.ac`` simulation and
parses per-frequency magnitude and phase samples for gain, crossover frequency,
and phase-margin checks.

Note: the live invocation path is calibrated to documented ngspice ``-b``
``print`` output ("``v(node) = value``"); verify against your ngspice build.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# A node-voltage line from ngspice batch `print`: "v(vcc) = 3.300000e+00".
_NUMBER_PATTERN = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
_VOLTAGE_RE = re.compile(rf"v\(([^)]+)\)\s*=\s*({_NUMBER_PATTERN})", re.IGNORECASE)
# ngspice 42+ `print all` emits node rows as `mid = 2.500000e+00`.
# Keep the identifier deliberately narrow so branch-current rows such as
# `v1#branch = ...` are not misclassified as node voltages.
_BARE_NODE_VOLTAGE_RE = re.compile(
    rf"^\s*([A-Za-z_][A-Za-z0-9_.$:+-]*)\s*=\s*({_NUMBER_PATTERN})\s*$",
    re.MULTILINE,
)

# Transient waveform: ngspice .tran print output can have optional integer index:
# "0.000000e+00  3.300000e+00" (time<space>value)  OR
# "0  0.000000e+00  3.300000e+00" (index<space>time<space>value)
_TRAN_ROW_RE = re.compile(
    r"^\s*(?:\d+\s+)?"  # optional leading integer index
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # time
    r"\s+"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # voltage
    r"\s*$"
)

# AC analysis: ngspice batch `print` emits magnitude and phase on separate lines:
#   "v(vout)  = 1.234000e+00"  (magnitude, when using `print vm(vout)`)
#   "v(vout)  = -45.000000"    (phase degrees, when using `print vp(vout)`)
# The frequency-column row looks like:
#   "frequency  = 1.000000e+03"
_AC_FREQ_RE = re.compile(
    r"^\s*frequency\s*=\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)",
    re.IGNORECASE,
)
# ngspice AC print rows: optional index column + freq + magnitude (+ optional phase)
# "1.000000e+02   3.300000e+00   -4.500000e+01"  (freq, mag, phase)  OR
# "0  1.000000e+02   3.300000e+00   -4.500000e+01"  (idx, freq, mag, phase)
_AC_ROW_RE = re.compile(
    r"^\s*(?:\d+\s+)?"  # optional leading integer index
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # frequency
    r"\s+"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # magnitude
    r"(?:\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?))?"  # optional phase (degrees)
    r"\s*$"
)


_SPICE_END_LINE = ".end\n"
_NGSPICE_NOT_INSTALLED_REASON = "ngspice not installed"


@dataclass
class SpiceResult:
    """Result of an ngspice operating-point run.

    ``status`` is one of ``"ok"``, ``"skipped"`` (ngspice not installed), or
    ``"error"`` (ngspice ran but failed / timed out).
    """

    status: str
    node_voltages: dict[str, float] = field(default_factory=dict)
    raw_output: str = ""
    reason: str = ""


@dataclass
class TransientWaveform:
    """Time-series waveform from a transient analysis run.

    Attributes
    ----------
    node:
        Net name the waveform was measured on (e.g. ``"vout"``).
    times_s:
        Simulation time samples in seconds.
    voltages_v:
        Corresponding voltage samples in volts.
    """

    node: str
    times_s: list[float] = field(default_factory=list)
    voltages_v: list[float] = field(default_factory=list)

    @property
    def min_v(self) -> float | None:
        return min(self.voltages_v) if self.voltages_v else None

    @property
    def max_v(self) -> float | None:
        return max(self.voltages_v) if self.voltages_v else None

    @property
    def final_v(self) -> float | None:
        return self.voltages_v[-1] if self.voltages_v else None

    def steady_state_window(self, *, last_fraction: float = 0.2) -> list[float]:
        """Return voltages in the last *last_fraction* of the simulation time."""
        if not self.voltages_v:
            return []
        n = max(1, int(len(self.voltages_v) * last_fraction))
        return self.voltages_v[-n:]

    def ripple_v(self, *, last_fraction: float = 0.2) -> float:
        """Peak-to-peak voltage ripple in the steady-state window."""
        window = self.steady_state_window(last_fraction=last_fraction)
        return max(window) - min(window) if len(window) >= 2 else 0.0

    def startup_time_s(self, target_v: float, *, threshold: float = 0.9) -> float | None:
        """Time (in seconds) when the waveform first reaches *threshold* × *target_v*.

        Returns ``None`` if the voltage never reaches the threshold.
        """
        threshold_v = threshold * target_v
        for t, v in zip(self.times_s, self.voltages_v, strict=False):
            if v >= threshold_v:
                return t
        return None


@dataclass
class TransientResult:
    """Result of an ngspice transient analysis run.

    ``status`` is one of ``"ok"``, ``"skipped"`` (ngspice not installed), or
    ``"error"`` (ngspice ran but failed / timed out).
    """

    status: str
    waveforms: dict[str, TransientWaveform] = field(default_factory=dict)
    raw_output: str = ""
    reason: str = ""


@dataclass
class AcSample:
    """One frequency-domain measurement from an AC analysis.

    Attributes
    ----------
    freq_hz:
        Frequency in hertz.
    magnitude_db:
        Gain magnitude in dB (20 * log10 of the voltage ratio).
    phase_deg:
        Phase angle in degrees (``None`` if not captured).
    """

    freq_hz: float
    magnitude_db: float
    phase_deg: float | None = None


@dataclass
class AcResult:
    """Result of an ngspice AC analysis run.

    ``status`` is one of ``"ok"``, ``"skipped"`` (ngspice not installed), or
    ``"error"`` (ngspice ran but failed / timed out).

    Attributes
    ----------
    samples:
        Parsed frequency-domain samples (sorted by ``freq_hz`` ascending).
    node:
        Net name that was probed.
    """

    status: str
    samples: list[AcSample] = field(default_factory=list)
    node: str = ""
    raw_output: str = ""
    reason: str = ""

    @property
    def frequencies_hz(self) -> list[float]:
        """All frequency values in the sweep, ascending."""
        return [s.freq_hz for s in self.samples]

    @property
    def magnitudes_db(self) -> list[float]:
        """Magnitude samples in dB, corresponding to :attr:`frequencies_hz`."""
        return [s.magnitude_db for s in self.samples]

    @property
    def phases_deg(self) -> list[float | None]:
        """Phase samples in degrees, corresponding to :attr:`frequencies_hz`."""
        return [s.phase_deg for s in self.samples]

    def gain_at_hz(self, freq_hz: float) -> float | None:
        """Interpolated gain in dB at *freq_hz* (linear interpolation in log-freq space).

        Returns ``None`` when the frequency is outside the sweep range or when
        there are fewer than two samples.
        """
        import math

        if len(self.samples) < 2:
            return None
        if freq_hz <= 0:
            return None
        freqs = self.frequencies_hz
        if freq_hz < freqs[0] or freq_hz > freqs[-1]:
            return None
        log_f = math.log10(freq_hz)
        for i in range(len(freqs) - 1):
            if freqs[i] <= freq_hz <= freqs[i + 1]:
                log_f0 = math.log10(freqs[i])
                log_f1 = math.log10(freqs[i + 1])
                if log_f1 == log_f0:
                    return self.samples[i].magnitude_db
                t = (log_f - log_f0) / (log_f1 - log_f0)
                return self.samples[i].magnitude_db + t * (
                    self.samples[i + 1].magnitude_db - self.samples[i].magnitude_db
                )
        return None

    def crossover_hz(self) -> float | None:
        """Frequency (Hz) where gain first crosses 0 dB (descending edge).

        Returns ``None`` if gain never crosses 0 dB.
        """
        for i in range(len(self.samples) - 1):
            m0 = self.samples[i].magnitude_db
            m1 = self.samples[i + 1].magnitude_db
            if m0 >= 0.0 >= m1:
                # linear interpolation for zero-crossing in log-freq space
                if m0 == m1:
                    return self.samples[i].freq_hz
                t = m0 / (m0 - m1)
                import math

                log_f = math.log10(self.samples[i].freq_hz) + t * (
                    math.log10(self.samples[i + 1].freq_hz) - math.log10(self.samples[i].freq_hz)
                )
                return 10**log_f
        return None

    def phase_margin_deg(self) -> float | None:
        """Phase margin in degrees at the gain crossover frequency.

        Returns ``None`` when gain never crosses 0 dB or phase data is absent
        at the crossover point.
        """
        fc = self.crossover_hz()
        if fc is None:
            return None
        # Find sample nearest to crossover
        nearest = min(self.samples, key=lambda s: abs(s.freq_hz - fc))
        if nearest.phase_deg is None:
            return None
        return nearest.phase_deg + 180.0


def ngspice_available() -> bool:
    """True if an ``ngspice`` executable is on PATH."""
    return shutil.which("ngspice") is not None


def ngspice_version() -> str:
    """Return the detected ngspice version token, or an empty string."""
    binary = shutil.which("ngspice")
    if binary is None:
        return ""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = result.stdout + "\n" + result.stderr
    match = re.search(r"ngspice-[^\s:]+", output, re.IGNORECASE)
    return match.group(0) if result.returncode == 0 and match else ""


def with_op_control(netlist: str) -> str:
    """Insert a ``.op`` control block before the final ``.end`` of *netlist*.

    Adds a batch control block that runs the operating point and prints every
    node voltage so the output can be parsed deterministically.
    """
    control = ".control\nop\nprint all\n.endc\n"
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, control.rstrip("\n"))
            return "\n".join(lines) + "\n"
    # No .end found — append control + .end.
    return netlist.rstrip("\n") + "\n" + control + _SPICE_END_LINE


def with_tran_control(netlist: str, step_s: float, stop_s: float, node: str) -> str:
    """Insert a ``.tran`` control block for transient analysis.

    Parameters
    ----------
    netlist:
        SPICE netlist string (must end with ``.end``).
    step_s:
        Timestep size in seconds (e.g. ``1e-9`` for 1 ns).
    stop_s:
        Simulation stop time in seconds (e.g. ``100e-6`` for 100 µs).
    node:
        Net name to print (e.g. ``"vout"``).
    """
    control = f".control\ntran {step_s:g} {stop_s:g}\nprint v({node})\n.endc\n"
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, control.rstrip("\n"))
            return "\n".join(lines) + "\n"
    return netlist.rstrip("\n") + "\n" + control + _SPICE_END_LINE


def parse_op_output(text: str) -> dict[str, float]:
    """Parse node voltages from supported ngspice batch output formats."""
    voltages = {match.group(1).lower(): float(match.group(2)) for match in _BARE_NODE_VOLTAGE_RE.finditer(text)}
    for match in _VOLTAGE_RE.finditer(text):
        voltages[match.group(1).lower()] = float(match.group(2))
    return voltages


def parse_tran_output(text: str, node: str) -> TransientWaveform:
    """Parse ngspice transient print output into a :class:`TransientWaveform`.

    ngspice batch ``print v(node)`` emits rows of the form::

        0.000000e+00  3.300000e+00
        1.000000e-09  3.301000e+00

    Parameters
    ----------
    text:
        Raw stdout/stderr output from ngspice batch mode.
    node:
        The node name that was printed (used to populate :attr:`TransientWaveform.node`).
    """
    waveform = TransientWaveform(node=node)
    for line in text.splitlines():
        m = _TRAN_ROW_RE.match(line)
        if m:
            waveform.times_s.append(float(m.group(1)))
            waveform.voltages_v.append(float(m.group(2)))
    return waveform


def run_operating_point(netlist: str, *, timeout_s: float = 30.0) -> SpiceResult:
    """Run a DC operating point on *netlist* with ngspice (skip-aware).

    Returns a :class:`SpiceResult`. When ngspice is not installed the status is
    ``"skipped"`` so callers can record missing-evidence rather than fail.
    """
    if not ngspice_available():
        return SpiceResult(status="skipped", reason=_NGSPICE_NOT_INSTALLED_REASON)

    sim_netlist = with_op_control(netlist)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False, encoding="utf-8") as handle:
            handle.write(sim_netlist)
            tmp_path = Path(handle.name)
        proc = subprocess.run(
            ["ngspice", "-b", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return SpiceResult(status="error", raw_output=output, reason=f"ngspice exited {proc.returncode}")
        return SpiceResult(status="ok", node_voltages=parse_op_output(output), raw_output=output)
    except subprocess.TimeoutExpired:
        return SpiceResult(status="error", reason=f"ngspice timed out after {timeout_s}s")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def run_transient(
    netlist: str,
    node: str,
    *,
    step_s: float = 1e-9,
    stop_s: float = 100e-6,
    timeout_s: float = 60.0,
) -> TransientResult:
    """Run a transient (``.tran``) simulation on *netlist* and return a waveform.

    Parameters
    ----------
    netlist:
        SPICE netlist to simulate.  Must not already contain a ``.tran`` or
        ``.control`` block — this function injects one automatically.
    node:
        Net name to capture (e.g. ``"vout"``).
    step_s:
        Timestep in seconds.
    stop_s:
        Stop time in seconds.
    timeout_s:
        Maximum wall-clock time for the ngspice process.

    Returns
    -------
    TransientResult
        ``status="skipped"`` when ngspice is absent; ``status="error"`` on
        timeout or non-zero exit; ``status="ok"`` with parsed waveform data.
    """
    if not ngspice_available():
        return TransientResult(status="skipped", reason=_NGSPICE_NOT_INSTALLED_REASON)

    sim_netlist = with_tran_control(netlist, step_s, stop_s, node)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False, encoding="utf-8") as handle:
            handle.write(sim_netlist)
            tmp_path = Path(handle.name)
        proc = subprocess.run(
            ["ngspice", "-b", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return TransientResult(status="error", raw_output=output, reason=f"ngspice exited {proc.returncode}")
        waveform = parse_tran_output(output, node)
        return TransientResult(status="ok", waveforms={node: waveform}, raw_output=output)
    except subprocess.TimeoutExpired:
        return TransientResult(status="error", reason=f"ngspice timed out after {timeout_s}s")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def with_ac_control(
    netlist: str,
    *,
    variation: str = "dec",
    points_per_decade: int = 20,
    start_hz: float = 1.0,
    stop_hz: float = 10e6,
    node: str = "vout",
) -> str:
    """Insert a ``.ac`` control block for AC sweep analysis.

    Parameters
    ----------
    netlist:
        SPICE netlist string (must end with ``.end``).
    variation:
        ngspice sweep type: ``"dec"`` (decades), ``"oct"`` (octaves), or
        ``"lin"`` (linear).
    points_per_decade:
        Number of frequency points per decade/octave (or total for linear).
    start_hz:
        Start frequency in hertz.
    stop_hz:
        Stop frequency in hertz.
    node:
        Net name to print gain (uses ``vm(node)`` for magnitude, ``vp(node)``
        for phase in degrees).
    """
    control = (
        f".control\nac {variation} {points_per_decade} {start_hz:g} {stop_hz:g}\nprint vm({node}) vp({node})\n.endc\n"
    )
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, control.rstrip("\n"))
            return "\n".join(lines) + "\n"
    return netlist.rstrip("\n") + "\n" + control + _SPICE_END_LINE


def parse_ac_output(text: str, node: str) -> list[AcSample]:
    """Parse ngspice AC ``print vm(node) vp(node)`` batch output.

    ngspice AC batch output format (two columns per row, or three when phase is
    requested together with magnitude)::

        1.000000e+00   3.300000e+00   -0.000000e+00
        1.258925e+00   3.299800e+00   -1.000000e-02

    where columns are: frequency, magnitude (linear), phase (degrees).

    Parameters
    ----------
    text:
        Raw stdout+stderr from ngspice batch mode.
    node:
        Net name used when printing (for the returned :class:`AcSample` ``node``
        attribute — the samples themselves don't carry per-sample node info).

    Returns
    -------
    list[AcSample]
        Samples sorted ascending by frequency.  Magnitude is converted to dB
        via ``20 * log10(|mag|)``; zero-magnitude samples get ``-inf`` dB.
    """
    import math

    samples: list[AcSample] = []
    for line in text.splitlines():
        m = _AC_ROW_RE.match(line)
        if m:
            freq = float(m.group(1))
            mag_linear = float(m.group(2))
            phase = float(m.group(3)) if m.group(3) is not None else None
            if freq <= 0:
                continue
            mag_db = 20.0 * math.log10(mag_linear) if mag_linear > 0 else float("-inf")
            samples.append(AcSample(freq_hz=freq, magnitude_db=mag_db, phase_deg=phase))
    samples.sort(key=lambda s: s.freq_hz)
    return samples


def run_ac(
    netlist: str,
    node: str,
    *,
    variation: str = "dec",
    points_per_decade: int = 20,
    start_hz: float = 1.0,
    stop_hz: float = 10e6,
    timeout_s: float = 30.0,
) -> AcResult:
    """Run an AC sweep on *netlist* and return parsed frequency-domain samples.

    Parameters
    ----------
    netlist:
        SPICE netlist to simulate (without ``.ac`` or ``.control`` block).
    node:
        Net name to probe.
    variation:
        ngspice sweep type (``"dec"``, ``"oct"``, or ``"lin"``).
    points_per_decade:
        Points per decade/octave, or total points for linear.
    start_hz:
        Start frequency in hertz.
    stop_hz:
        Stop frequency in hertz.
    timeout_s:
        Wall-clock timeout for ngspice.

    Returns
    -------
    AcResult
        ``status="skipped"`` when ngspice is absent; ``status="error"`` on
        timeout or non-zero exit; ``status="ok"`` with parsed samples.
    """
    if not ngspice_available():
        return AcResult(status="skipped", node=node, reason=_NGSPICE_NOT_INSTALLED_REASON)

    sim_netlist = with_ac_control(
        netlist,
        variation=variation,
        points_per_decade=points_per_decade,
        start_hz=start_hz,
        stop_hz=stop_hz,
        node=node,
    )
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False, encoding="utf-8") as handle:
            handle.write(sim_netlist)
            tmp_path = Path(handle.name)
        proc = subprocess.run(
            ["ngspice", "-b", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return AcResult(status="error", node=node, raw_output=output, reason=f"ngspice exited {proc.returncode}")
        samples = parse_ac_output(output, node)
        return AcResult(status="ok", samples=samples, node=node, raw_output=output)
    except subprocess.TimeoutExpired:
        return AcResult(status="error", node=node, reason=f"ngspice timed out after {timeout_s}s")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

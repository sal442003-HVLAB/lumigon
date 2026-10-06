# P-9710 flash range check (V2)

The range selection uses GP replies paired with the immediately preceding MV,
with autorange disabled and the same 0.1 ms integration used for acquisition.
The operator subsequently observed GP stopping at 50 during known overload in
both R5 and R6. The lab policy now uses this empirical saturation reference:
`range use = 100 × abs(raw GP) / 50`. 10–90% of this observed limit is an
engineering target; the upper ceiling corresponds to raw GP=45, so GP=50 is
rejected even when no overload error code is emitted. This is not a confirmed
manufacturer definition, full-scale calibration, or uncertainty estimate.
The GP zero origin and linearity in unsaturated ranges still need hardware
validation. R(n−1) has less gain and
more capacity; R(n+1) has more gain. The decade factor only predicts a candidate:
the new range is always checked with actual GP readings.

At each C/Gamma point, a separate 5.5 s precheck polls GP after every numeric MV.
A complete flash must be resolved before selecting the range. If the peak is
below 10%, a more sensitive range is tried only when the predicted use is at
most 90%. Otherwise the safer range is retained, labelled low utilization.
Ranges rejected above 90% at that point are remembered to prevent oscillation.
No flash or a failed GP query must not cause a blind gain increase.

The main waveform is captured on a fixed range. GP is read immediately after
any new MV maximum or minimum, before the next MV. This guards an increase in
sampled peak after precheck without adding a GP query to every waveform sample.
An overload reply or GP above 90% discards the entire acquisition and repeats
precheck and acquisition on a less sensitive range. Missing/non-finite GP or
zero resolved GP at an optical flash cannot yield an accepted point. An explicit
GP underload status during darkness is allowed, but cannot replace a positive
GP check of the bright phase.

MV transaction timestamps are retained; GP transactions add real gaps to the
sample cadence, and are not counted as additional waveform samples. Sampling
still cannot prove absence of brief unsampled peaks. Integration accuracy and
GP behavior need validation on the actual P-9710 firmware and source pulse
shape. Mock-meter tests validate control flow, not physical calibration. The
first hardware check should compare repeated R5/R4 measurements at the formerly
clipped angle, inspect GP while illuminated, and compare waveform cadence and
computed effective values. Low use is a warning, not a precision guarantee.

Measurement and its progress popup show range, peak range use, and state. The
peak display is reset at each capture so dark samples cannot hide a bright peak.
Accepted V2 CSV schema 2.3 stores the final range, normalized precheck/acquisition
peaks, their maximum, raw GP peaks, the reference value and observation basis,
GP check count, selection attempt count, method, and status. The loader checks
the raw/normalized relationship. Measured lux, peak illuminance, integral,
E-effective, and I-effective are NEVER multiplied by the GP normalization.
It saves accepted points only. Schema 2.0/2.1 remains loadable with unverified
range checks. Schema 2.2 retains its original GP percentages and is not rescaled.
Plot exports identify GP metadata and the empirical saturation reference.

## Hardware discrepancy investigation

The operator observed an overload indication in the manufacturer's software
that was not detected by the GP-based check. That check must therefore not be
presented as validated hardware overload detection. The display and plot export
say that hardware overload detection is unverified; changing the percentage
scale or threshold without the actual replies would hide the problem.

One confirmed driver defect was reproduced: a `?2` reply to SR5 was discarded
by `command()`. Commands now reject explicit error replies. Measurement reads
GR, GS0, and GS3 after configuration to check the actual range, fixed-gain mode,
and CW integration. A configuration mismatch rejects the acquisition. An
explicit overload during configuration causes a retry at less gain.

Each run also writes `<measurement-stem>_diagnostics.csv` beside the measurement
CSV, tracing commands and exact replies with phase, point, requested range,
and transaction timestamps. The diagnostics distinguish a rejected setting,
different effective integration, literal GP scale, and a missing/status reply.
The trace is closed and the driver's prior callback restored on success,
failure, or abort. Compare the main CSV and diagnostic trace from the same
previously overloaded angle before selecting another overload detection method.

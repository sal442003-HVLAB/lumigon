# P-9710 flash range check (V2)

The range selection uses GP replies paired with the immediately preceding MV,
with autorange disabled and the same 0.1 ms integration used for acquisition.
10–90% is an engineering target; 90% is a software acceptance ceiling, not a
manufacturer specification or an uncertainty estimate. R(n−1) has less gain and
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
Accepted V2 CSV schema 2.2 stores the final range, separate precheck/acquisition
GP peaks, their maximum, GP check count, selection attempt count, method, and
status. It saves accepted points only. Schema 2.0/2.1 remains loadable but its
range checks are unverified. Plot exports state whether GP metadata exists.

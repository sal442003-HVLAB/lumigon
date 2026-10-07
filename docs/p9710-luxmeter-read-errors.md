# P-9710 Luxmeter read errors

The operator's 2026-10-07 screenshot identifies firmware `P9710 V4.4` and
`SS0: ?1` during CW Maximum continuous reading. The P-9710 manufacturer's
2007 operating manual, V1.20 (describing firmware V4.7), defines `?1` as
"command not allowed". That alone does not distinguish an older firmware
limitation from a device state that disallows the command.

CW configuration still sends the requested `SS0`/`SS1`. If and only if `SS0`
returns `?1`, the driver queries `GS7`. This is an 8-bit flag field; only bit 1
(mask `0x02`, manual §15.3.9) indicates synchronization active. The initial
fallback incorrectly required the whole field to be zero. The operator's next
screenshot returned 60 (`00111100`), which has synchronization disabled despite
other flags being set. The fallback now checks only that bit, after validating
an integer flag value in 0..255. Active synchronization, invalid, missing or
error replies reject the acquisition with an actionable message.
Other command errors are never ignored. No substitute calibration/wavelength
command is sent. Existing Measurement range/auto/integration readbacks remain.

Continuous reading stops all polling timers before opening the first read
error dialog. It also stops on a disconnected-meter attempt. Old displayed
results and cached last readings are cleared after failure. Restart requires
an explicit operator action.

An independent defect was found in MI configuration: `SM` uses **10 ms ticks**,
not milliseconds (manual §15.3.2). A requested 600 ms window must send `SM60`,
not `SM600` (6 seconds). The driver's reply wait already used the requested
milliseconds, so the old conversion could time out while the meter was still
measuring. Windows must be at least 100 ms and use 10 ms steps. The Effective
page reflects that limit; flash detection has a finite default timeout.
The initial Effective error was not captured in the screenshot, so the SM
defect is a possible cause of that report, not a hardware-confirmed diagnosis.

Regression checks cover rejected synchronization commands, strict readback
fallback, SM unit conversion and reply timing, a bounded trigger wait, and
timer shutdown before an error dialog. They use simulated replies. Actual
V4.4 behavior still needs an operator retry; unknown readbacks remain blocked.

Manufacturer manual mirror:
https://manualzz.com/doc/25024185/gigahertz-optik-p-9710-1--2-optometer-operating-manual

## Effective setup rejects SN1

A later operator screenshot shows `SN1: ?1` on the Effective page. This
fails during the fast CW setup used to detect the reference flash, before
`MV` triggering or `MI` acquisition. `SN1` requests a 0.1 ms CW integration;
it does not set the Effective measurement window. The V4.7 manual documents
this value, but the V4.4 screenshot does not establish why the setter was
disallowed (firmware capability, current state, or another restriction).

If an `SN` setter returns exactly `?1`, the driver now queries `GS3`, whose
unit is also 0.1 ms. It continues only when the complete numeric reply is
finite and exactly matches the requested tick count. In particular, `GS3=1`
permits `SN1: ?1` to proceed; `GS3=1000` means 100 ms and must block the flash
measurement. Unknown, malformed, missing or error replies also block it.
The error reports the returned and required settings and asks the operator
to stop any front-panel measurement and verify the required CW integration.
No slower integration or altered threshold is
silently substituted. Other setter error codes retain their original failure.

Flash detection now verifies range, autorange and integration even when the
setter succeeds. This shared setup covers synchronized Effective, adaptive
Effective and flash timing. Simulated regression tests exercise the full
Effective command sequence through an unchanged `MI` value with matching
readback, and prove that no `MV` or `MI` is issued with a mismatched setting.
Hardware resolution still requires an operator retry and, if blocked, the
new GS3 readback from the error. This is a verified-state fallback, not proof
that V4.4 always accepts remote integration changes.

## Explicit pulse period and fresh results

The operator subsequently confirmed that CW works when attempted first, while
Effective still fails. This observation does not identify the new command or
GS3 readback; it must not be treated as proof of firmware support or a solved
Effective acquisition. A UI regression models working CW at 100 ms, rejected
Effective setup at 0.1 ms, and a successful return to CW continuous reading.
It checks that the worker is released and only one error dialog is emitted.

The Effective pulse-period field now starts at zero, including after
connection/disconnection, instead of retaining a laboratory example of
3.170 s. The operator must enter at least 0.05 s before a worker can start.
Each new attempt clears old E-effective, I-effective, trigger, cached results
and GP utilization. The bar resets to zero with `Unavailable`, so a previous
percentage cannot appear to describe the new attempt. A manually entered
period remains available for repeated measurements in the same session.

## Complete serial acknowledgements

The next screenshot identified `SM60: ?1`. The operator then reported
`SU0.2: ?1` on another attempt while all CW/peak modes worked, and said the
Remote RS232 mode did not connect. The changing error command is not proof
of a firmware limitation, nor proof of response misattribution. We no longer
present switching to Remote RS232 as the solution on this particular meter.

A definite transport defect was found: setters reduced the read timeout to
50 ms and treated both `b''` (no bytes received) and `b'\n'` (successful LF
acknowledgement) as success. A delayed response could consequently be lost
by the next input-buffer reset or consumed under the next command's name.
The manufacturer's V4.7 manual §15.1/§15.4 documents an LF terminator for
each command response, including successful setters with no numeric payload.

Setters now use the configured response timeout (normally 3 seconds), and
both setters and queries require a complete LF-terminated response. Serial
exchanges are protected by a lock. A missing or incomplete frame blocks any
subsequent command until disconnect/reconnect, preventing a late packet from
being treated as the next command's response. A bare LF remains a valid
setter acknowledgement. Actual `?1` errors still fail; `SU` and `SM` are
never silently bypassed or replaced with a software intensity calculation.

Effective error dialogs now offer Show Details with the last 16 literal
command/reply pairs and transaction durations. Missing and incomplete frames
have explicit markers; complete empty acknowledgements appear as `''`.
Simulated tests cover delayed acknowledgements/rejections, absent/partial
frames, subsequent-send blocking, MI timeout preservation, genuine SU/SM
rejection and the diagnostic content. This corrects a verified code defect;
it does not yet establish the reason for the observed hardware rejection.

## Low Effective values and visible timing controls

The operator subsequently obtained a native MI result: the screenshot shows
E-effective 1.5117 lx, I-effective 37.79 cd at 5 m, and a trigger sample of
45.513 lx with an entered period of 4.1800 s. This is not evidence that the
full pulse was captured. Effective illuminance depends on pulse area, peak
and C (manufacturer Appendix 17.1), so peak alone cannot establish an
expected Effective value. Native values are not rescaled toward an expected
number. Existing static offset is retained (`SZ0` selects the SO offset;
it does not itself clear that offset), and source period, pulse duration,
static offset and complete window coverage remain hardware checks.

Two concrete scheduling issues were corrected. Fixed-threshold detection
previously initialized the preceding sample to zero, allowing the very first
bright sample to be treated as a rising edge even when already mid-flash.
It now requires an observed below-threshold sample before a bright crossing;
a genuine underload may arm the dark side, and non-finite samples fail.
After Effective configuration, the next acquisition start is selected from
future cycles of the entered period (with 50 ms preparation lead), so setup
delays cannot automatically trigger an expired prediction. This also applies
to the adaptive MI path. Neither fix verifies the user-entered period or
proves optical coverage under source jitter or operating-system delays.

The single-flash timing setup rejects non-finite values, windows that end
before the predicted edge (window <= pre-trigger), and windows at least as
long as the period, before any device I/O. C is limited to its documented
0.0001..5.9999 s range. The existing "Advanced settings" section was collapsed
in the screenshot, not empty. It now starts expanded, showing pre-trigger,
MI window, threshold and C; it still supports collapsing. A timing note
explains full-pulse coverage, and inputs are disabled during acquisition.
Results now say "PC schedule offset", rather than implying a measured
optical synchronization error. The returned native MI and lux-to-candela
conversion are unchanged.

Regression tests cover starting in the bright phase, constant light, an
underload-to-bright transition, setup delays spanning multiple periods,
impossible timing, invalid C, and Advanced visibility/toggling. A rectangular
source model demonstrates selecting a future full pulse rather than its
tail. UI inspection at 1366x768 confirmed all four Advanced controls appear
with bounded vertical scrolling. Actual flash validation remains pending.

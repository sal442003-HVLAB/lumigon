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
to stop any front-panel measurement, select Mode / Remote RS232, and set the
required CW integration. No slower integration or altered threshold is
silently substituted. Other setter error codes retain their original failure.

Flash detection now verifies range, autorange and integration even when the
setter succeeds. This shared setup covers synchronized Effective, adaptive
Effective and flash timing. Simulated regression tests exercise the full
Effective command sequence through an unchanged `MI` value with matching
readback, and prove that no `MV` or `MI` is issued with a mismatched setting.
Hardware resolution still requires an operator retry and, if blocked, the
new GS3 readback from the error. This is a verified-state fallback, not proof
that V4.4 always accepts remote integration changes.

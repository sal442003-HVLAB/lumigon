# P-9710 Luxmeter read errors

The operator's 2026-10-07 screenshot identifies firmware `P9710 V4.4` and
`SS0: ?1` during CW Maximum continuous reading. The P-9710 manufacturer's
2007 operating manual, V1.20 (describing firmware V4.7), defines `?1` as
"command not allowed". That alone does not distinguish an older firmware
limitation from a device state that disallows the command.

CW configuration still sends the requested `SS0`/`SS1`. If and only if `SS0`
returns `?1`, the driver queries `GS7`. It continues only for an exact numeric
zero, proving all flags including synchronization are off. Unknown, nonzero,
missing or error replies reject the acquisition with an actionable message.
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

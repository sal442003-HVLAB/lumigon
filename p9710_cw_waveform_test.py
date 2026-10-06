"""Standalone P-9710 CW waveform capture test.

This file does NOT modify or depend on the Lumigon GUI workflow.  It connects
straight to the existing P9710 driver, fixes the selected current range, sets
the fastest verified CW integration (SN1 = 0.1 ms), repeatedly reads MV, and
writes the raw time series to CSV for offline comparison with an oscilloscope.

Default lab setup:
    Port: COM7
    Range: R5
    Capture: 30 s

Usage:
    python p9710_cw_waveform_test.py
    python p9710_cw_waveform_test.py --port COM7 --range 5 --seconds 30
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import time
from datetime import datetime
from pathlib import Path

from p9710 import P9710, P9710Error


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture raw P-9710 CW MV samples for flash-waveform analysis."
    )
    parser.add_argument("--port", default="COM7", help="P-9710 serial port (default: COM7)")
    parser.add_argument(
        "--range",
        dest="range_id",
        type=int,
        default=5,
        choices=range(0, 8),
        help="Fixed P-9710 range R0..R7 (default: R5)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=30.0,
        help="Capture duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output CSV path. Default creates a timestamped file.",
    )
    return parser.parse_args()


def status_code(exc: Exception) -> str:
    text = str(exc)
    if "?16" in text:
        return "overload"
    if "?32" in text:
        return "underload"
    if "No response" in text or "No reliable response" in text:
        return "no_response"
    return "error"


def main():
    args = parse_args()

    if args.seconds <= 0:
        raise SystemExit("--seconds must be positive.")

    output = Path(args.output) if args.output else Path(
        f"p9710_cw_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    meter = P9710(args.port)
    rows = []
    valid_mid_times = []
    valid_values = []

    print("P-9710 standalone CW waveform capture")
    print("--------------------------------------")
    print(f"Port       : {args.port}")
    print(f"Fixed range: R{args.range_id}")
    print(f"Capture    : {args.seconds:.1f} s")
    print("Integration: 0.1 ms (SN1)")
    print("CW sync    : OFF")
    print()

    try:
        version = meter.connect()
        print(f"Connected  : {version} | unit {meter.unit or '—'}")

        # Fastest verified CW configuration, with one fixed range for the whole
        # capture. Do not autorange while measuring a waveform.
        meter.configure_cw(
            integration_ms=0.1,
            range_id=args.range_id,
            sync_enabled=False,
        )

        # Allow the changed mode/range to settle before starting the clock.
        time.sleep(0.10)

        capture_start = time.perf_counter()
        deadline = capture_start + float(args.seconds)
        index = 0

        print("Capturing... Ctrl+C cancels and still saves collected samples.")

        try:
            while time.perf_counter() < deadline:
                index += 1
                wall_time = datetime.now().isoformat(timespec="milliseconds")

                try:
                    value, raw, t1, t2 = meter.read_mv(
                        attempts=1,
                        retry_delay_s=0.0,
                    )
                    t_mid = (t1 + t2) / 2.0
                    elapsed = t_mid - capture_start
                    query_ms = (t2 - t1) * 1000.0

                    rows.append(
                        {
                            "sample": index,
                            "wall_time": wall_time,
                            "elapsed_s": f"{elapsed:.9f}",
                            "mv_lx": f"{value:.9g}",
                            "raw_reply": raw,
                            "status": "ok",
                            "query_ms": f"{query_ms:.3f}",
                        }
                    )
                    if math.isfinite(value):
                        valid_mid_times.append(t_mid)
                        valid_values.append(float(value))

                except P9710Error as exc:
                    now = time.perf_counter()
                    rows.append(
                        {
                            "sample": index,
                            "wall_time": wall_time,
                            "elapsed_s": f"{now - capture_start:.9f}",
                            "mv_lx": "",
                            "raw_reply": str(exc),
                            "status": status_code(exc),
                            "query_ms": "",
                        }
                    )

        except KeyboardInterrupt:
            print("\nCapture interrupted by user; saving collected data.")

    finally:
        meter.disconnect()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample",
                "wall_time",
                "elapsed_s",
                "mv_lx",
                "raw_reply",
                "status",
                "query_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    intervals_ms = [
        (b - a) * 1000.0 for a, b in zip(valid_mid_times, valid_mid_times[1:]) if b > a
    ]

    ok_count = sum(row["status"] == "ok" for row in rows)
    underload_count = sum(row["status"] == "underload" for row in rows)
    overload_count = sum(row["status"] == "overload" for row in rows)
    no_response_count = sum(row["status"] == "no_response" for row in rows)

    print()
    print(f"Saved      : {output.resolve()}")
    print(f"Rows       : {len(rows)}")
    print(f"Valid MV   : {ok_count}")
    print(f"Underload  : {underload_count}")
    print(f"Overload   : {overload_count}")
    print(f"No response: {no_response_count}")

    if intervals_ms:
        print(f"Median dt  : {statistics.median(intervals_ms):.3f} ms")
        print(f"Mean dt    : {statistics.mean(intervals_ms):.3f} ms")

    if valid_values:
        print(f"Min MV     : {min(valid_values):.6g} lx")
        print(f"Max MV     : {max(valid_values):.6g} lx")

    print()
    print("Send the generated CSV back for comparison with the oscilloscope waveform.")


if __name__ == "__main__":
    main()

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from axis_profile_controls import attach_axis_profile_controls
from machine_config import P6_03
from main_window import MainWindow
from motion_controller import C_AXIS, GAMMA, MotionController
from motion_limit_controls import apply_axis_limits_to_controls
from motor_control_refinement import attach_motor_control_refinement
from tabbed_layout import organize_main_window_tabs
import measurement_runtime_v2 as runtime
import motion_limit_controls as limits_ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    window = MainWindow()
    attach_motor_control_refinement(window)
    attach_axis_profile_controls(window)
    organize_main_window_tabs(window)
    apply_axis_limits_to_controls(window)
    app.processEvents()
    yield window
    window.timer.stop()
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("axis,limit", [(GAMMA, 75.0), (C_AXIS, 120.0)])
def test_selected_bound_allows_moves_beyond_old_bound_and_rejects_crossing(axis, limit):
    writes = []
    registers = {}
    motion = MotionController(SimpleNamespace(
        read_s32=lambda slave, address: registers.get(address, 0),
        read_u16=lambda *args: 0,
        write_s32=lambda slave, address, value: (writes.append((address, value)), registers.update({address: value})),
        write_u16=lambda *args: writes.append(args),
    ))
    motion.verify_axis = lambda *_: None
    motion.verify_servo_selection = lambda *_: None
    motion.wait_for_target = lambda *args, **kwargs: None
    motion.get_current_angle = lambda *_: 0.0
    motion.set_axis_limit_deg(axis, limit)
    motion.move_absolute(axis, limit)
    assert writes[0] == (P6_03, motion.degree_to_puu(axis, limit))
    writes.clear()
    for target in (-limit - 0.1, limit + 0.1):
        with pytest.raises(RuntimeError, match="exceeds"):
            motion.move_absolute(axis, target)
    motion.get_current_angle = lambda *_: limit - 0.5
    with pytest.raises(RuntimeError, match="exceeds"):
        motion.jog(axis, 1.0)
    with pytest.raises(RuntimeError, match="exceeds"):
        motion.execute_relative(axis, 1.0)
    assert writes == []


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_invalid_limit_keeps_previous_bound(invalid):
    motion = MotionController(None)
    with pytest.raises(ValueError):
        motion.set_axis_limit_deg(GAMMA, invalid)
    assert motion.axis_limit_deg(GAMMA) == 60.0
    assert motion.axis_limit_deg(C_AXIS) == 80.0


def test_controls_sync_both_manual_and_scan_bounds_without_layout_changes(window):
    assert window.findChild(QLabel, "readOnlyNotice") is None
    for prefix, limit in (("gamma", 75.0), ("c", 120.0)):
        spin = getattr(window, f"{prefix}_limit_spin")
        box = getattr(window, f"{prefix}_profile_box")
        assert box.layout().getItemPosition(box.layout().indexOf(spin)) == (5, 1, 1, 1)
        assert box.layout().horizontalSpacing() == 8
        assert box.layout().verticalSpacing() == 7
        spin.setValue(limit)
        spin.editingFinished.emit()
        axis = GAMMA if prefix == "gamma" else C_AXIS
        assert window.motion.axis_limit_deg(axis) == limit
        assert getattr(window, f"{prefix}_panel").target_spin.minimum() == -limit
        assert getattr(window, f"{prefix}_panel").target_spin.maximum() == limit
        assert getattr(window, f"measurement_v2_{prefix}_start").minimum() == -limit
        assert getattr(window, f"measurement_v2_{prefix}_end").maximum() == limit


def test_limit_edit_is_rejected_during_motion_or_outside_new_bound(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(limits_ui.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    window.manual_motion_worker = object()
    window.gamma_limit_spin.setValue(70)
    window.gamma_limit_spin.editingFinished.emit()
    assert window.motion.axis_limit_deg(GAMMA) == 60
    assert window.gamma_limit_spin.value() == 60
    assert "finish" in warnings[-1]
    window.manual_motion_worker = None
    window.modbus = SimpleNamespace(is_connected=True, disconnect=lambda: None)
    window.motion.set_session_zero(0, 0)
    window.motion.get_current_angle = lambda *_: 40
    window.gamma_limit_spin.setValue(30)
    window.gamma_limit_spin.editingFinished.emit()
    assert window.gamma_limit_spin.value() == 60
    assert "currently at" in warnings[-1]


def test_measurement_precheck_uses_selected_controller_limit(window, monkeypatch):
    warnings = []
    calls = []
    monkeypatch.setattr(runtime.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(runtime.QMessageBox, "critical", lambda *args: None)
    def stop_before_acquisition(*args):
        calls.append(args)
        raise ValueError("Stop test before acquisition")
    monkeypatch.setattr(runtime, "_axis_values", stop_before_acquisition)
    window.modbus = SimpleNamespace(is_connected=True, disconnect=lambda: None)
    window.gamma_zero_puu = window.c_zero_puu = 0
    window.p9710_meter_holder = {"meter": SimpleNamespace(is_connected=True, disconnect=lambda: None)}
    runtime.attach_measurement_runtime_v2(window)
    # Bypass the input range so the independent preflight check is exercised.
    window.measurement_v2_c_end.setMaximum(150)
    window.measurement_v2_c_end.setValue(95)
    window.motion.set_axis_limit_deg(C_AXIS, 90)
    window.measurement_v2_start_button.click()
    assert "±90°" in warnings[-1]
    assert calls == []
    warnings.clear()
    window.motion.set_axis_limit_deg(C_AXIS, 100)
    window.measurement_v2_start_button.click()
    assert warnings == ["Stop test before acquisition"]
    assert calls[0][1] == 95

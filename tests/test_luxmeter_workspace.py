import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QLabel, QProgressBar, QPushButton, QSpinBox,
    QVBoxLayout, QWidget, QAbstractSpinBox, QTabWidget,
)

import p9710_mode_workspace as modes
from luxmeter_scroll_runtime import attach_luxmeter_scroll_runtime
from luxmeter_workspace_tabs import attach_luxmeter_workspace_tabs
from p9710_continuous_runtime import attach_p9710_continuous_runtime
from p9710_flash_timing_runtime import attach_p9710_flash_timing_runtime


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def workspace(app):
    window = QWidget()
    root = QVBoxLayout(window)
    window.luxmeter_box = QGroupBox("C&G", window)
    root.addWidget(window.luxmeter_box)
    window.luxmeter_tab = window
    modes.attach_p9710_mode_workspace(window)
    attach_p9710_continuous_runtime(window)
    yield window
    window.p9710_stop_continuous()
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.fixture
def instrument_workspace(app):
    from main_window import MainWindow
    from luxmeter_controls import attach_luxmeter_controls
    from tabbed_layout import organize_main_window_tabs
    window = MainWindow()
    attach_luxmeter_controls(window)
    organize_main_window_tabs(window)
    modes.attach_p9710_mode_workspace(window)
    attach_p9710_continuous_runtime(window)
    attach_luxmeter_workspace_tabs(window)
    attach_p9710_flash_timing_runtime(window)
    attach_luxmeter_scroll_runtime(window)
    window.main_tabs.setCurrentIndex(1)
    window.resize(1366, 768)
    window.show()
    for _ in range(4):
        app.processEvents()
    yield window
    window.p9710_stop_continuous()
    window.timer.stop()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_instrument_switch_retains_each_connected_device_settings_and_results(instrument_workspace, app):
    window = instrument_workspace
    selector = window.luxmeter_instrument_combo
    assert window.luxmeter_tab.findChildren(QTabWidget) == []
    window.luxmeter = SimpleNamespace(is_connected=True)
    window.luxmeter_port_combo.setCurrentText("COM9-custom")
    window.luxmeter_sensitivity_spin.setValue(12.345)
    window.luxmeter_lux_label.setText("Lux: 123.456 lx")
    window.luxmeter_id_label.setText("Firmware: CG-TEST")
    selector.setCurrentIndex(1)
    window.p9710_meter_holder["meter"] = SimpleNamespace(is_connected=True)
    window.p9710_port_combo.setCurrentText("COM7-custom")
    window.p9710_mode_combo.setCurrentIndex(6)
    window.p9710_effective_period_spin.setValue(2.5)
    result = window.p9710_mode_stack.widget(6).measurement_results_box.findChildren(QLabel)[0]
    result.setText("E-effective: 45.678 lx")
    selector.setCurrentIndex(0)
    assert window.luxmeter_port_combo.currentText() == "COM9-custom"
    assert window.luxmeter_sensitivity_spin.value() == 12.345
    assert window.luxmeter_lux_label.text() == "Lux: 123.456 lx"
    assert window.luxmeter_id_label.text() == "Firmware: CG-TEST"
    assert window.luxmeter.is_connected
    selector.setCurrentIndex(1)
    assert window.p9710_port_combo.currentText() == "COM7-custom"
    assert window.p9710_mode_combo.currentIndex() == 6
    assert window.p9710_effective_period_spin.value() == 2.5
    assert result.text() == "E-effective: 45.678 lx"
    assert window.p9710_meter_holder["meter"].is_connected
    assert selector.isEnabled()


@pytest.mark.parametrize("operation", ["cg_live", "cw", "effective", "timing", "continuous"])
def test_instrument_cannot_switch_during_acquisition(instrument_workspace, app, monkeypatch, operation):
    window = instrument_workspace
    selector = window.luxmeter_instrument_combo
    selector.setCurrentIndex(1)
    if operation == "cg_live":
        window.luxmeter_live_worker = SimpleNamespace(isRunning=lambda: True)
        clear = lambda: setattr(window, "luxmeter_live_worker", None)
    elif operation == "timing":
        window.p9710_flash_timing_worker = object()
        clear = lambda: setattr(window, "p9710_flash_timing_worker", None)
    elif operation == "continuous":
        window.p9710_continuous_timers[0].start(10000)
        clear = window.p9710_stop_continuous
    else:
        window.p9710_mode_worker_holder["worker"] = object()
        clear = lambda: window.p9710_mode_worker_holder.update(worker=None)
    window.refresh_luxmeter_instrument_selection()
    assert not selector.isEnabled()
    selector.setCurrentIndex(0)  # Programmatic changes must also be rejected.
    assert selector.currentIndex() == 1
    assert window.luxmeter_instrument_stack.currentIndex() == 1
    clear()
    window.refresh_luxmeter_instrument_selection()
    assert selector.isEnabled()
    selector.setCurrentIndex(0)
    assert window.luxmeter_instrument_stack.currentIndex() == 0


def test_mode_pages_keep_connection_and_advanced_controls_visible_with_scroll(instrument_workspace, app):
    window = instrument_workspace
    window.luxmeter_instrument_combo.setCurrentIndex(1)
    for mode in (0, 6, 2, 6, 0):
        window.p9710_mode_combo.setCurrentIndex(mode)
        for _ in range(4):
            app.processEvents()
        page = window.p9710_mode_stack.currentWidget()
        assert window.p9710_connection_box.parentWidget() is page
        assert window.p9710_mode_combo.parentWidget() is page.measurement_settings_box
        assert window.p9710_connection_box.isVisible()
        assert window.p9710_mode_combo.isVisible()
        assert window.p9710_mode_stack.geometry().bottom() < window.p9710_effective_box.height()
        assert window.p9710_flash_timing_section.y() > window.p9710_effective_box.geometry().bottom()
        if mode == 6:
            content = window.p9710_effective_advanced_section.content
            assert content.isVisible()
            assert all(spin.height() >= 16 for spin in content.findChildren(QAbstractSpinBox))
            assert window.luxmeter_scroll_areas[1].verticalScrollBar().maximum() > 0


@pytest.mark.parametrize("operation", ["cw", "effective", "timing"])
def test_instrument_selector_locks_at_worker_start_and_unlocks_on_finish(instrument_workspace, monkeypatch, operation):
    window = instrument_workspace
    window.luxmeter_instrument_combo.setCurrentIndex(1)
    window.p9710_meter_holder["meter"] = SimpleNamespace(is_connected=True)
    workers = []
    class PendingWorker(QObject):
        measured = Signal(object)
        failed = Signal(str)
        finished = Signal()
        def __init__(self, *args, parent=None, **kwargs):
            super().__init__(parent)
            workers.append(self)
        def start(self):
            assert not window.luxmeter_instrument_combo.isEnabled()
    if operation == "cw":
        monkeypatch.setattr(modes, "CWWorker", PendingWorker)
        page = window.p9710_mode_stack.widget(0)
        next(b for b in page.findChildren(QPushButton) if b.text() == "Read CW").click()
    elif operation == "effective":
        monkeypatch.setattr(modes, "EffectiveWorker", PendingWorker)
        window.p9710_mode_combo.setCurrentIndex(6)
        window.p9710_effective_period_spin.setValue(2.0)
        page = window.p9710_mode_stack.widget(6)
        next(b for b in page.findChildren(QPushButton) if b.text() == "Measure synchronized").click()
    else:
        import p9710_flash_timing_runtime as timing
        monkeypatch.setattr(timing, "PulseTimingWorker", PendingWorker)
        next(b for b in window.p9710_flash_timing_box.findChildren(QPushButton)
             if b.text() == "Measure period / duration").click()
    assert len(workers) == 1
    assert not window.luxmeter_instrument_combo.isEnabled()
    workers[0].finished.emit()
    assert window.luxmeter_instrument_combo.isEnabled()


class ImmediateWorker(QObject):
    measured = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, meter, settings, parent=None):
        super().__init__(parent)
        self.reading = meter.reading

    def start(self):
        self.measured.emit(self.reading)
        self.finished.emit()


@pytest.mark.parametrize("gp,expected,state", [
    (45.0, 90, "Within observed target"),
    (50.0, 100, "Above limit"),
    (None, 0, "Unavailable"),
])
def test_cw_display_uses_observed_limit_without_scaling_lux(workspace, monkeypatch, gp, expected, state):
    monkeypatch.setattr(modes, "CWWorker", ImmediateWorker)
    reading = SimpleNamespace(cw_lx=12.3456, peak_max_lx=23.0,
                              peak_min_lx=1.0, peak_to_peak_lx=22.0,
                              range_utilization_pct=gp, range_id=5)
    workspace.p9710_meter_holder["meter"] = SimpleNamespace(is_connected=True, reading=reading)
    page = workspace.p9710_mode_stack.widget(0)
    next(b for b in page.findChildren(QPushButton) if b.text() == "Read CW").click()
    bar = page.findChild(QProgressBar)
    assert bar.value() == expected
    assert state in bar.format()
    assert any(label.text() == "CW: 12.3456 lx" for label in page.findChildren(QLabel))
    assert workspace.p9710_last_cw_reading.range_utilization_pct == gp
    if gp is not None:
        assert any(f"raw GP {gp:g}" in label.text() for label in page.findChildren(QLabel))


def test_effective_display_does_not_double_photometric_results(workspace, monkeypatch):
    monkeypatch.setattr(modes, "EffectiveWorker", ImmediateWorker)
    workspace.p9710_meter_holder["meter"] = SimpleNamespace(
        is_connected=True, reading=SimpleNamespace(
            e_effective_lx=4.0, trigger_sample_lx=8.0,
            software_start_error_ms=0.1, range_utilization_pct=50.0, range_id=4,
        ),
    )
    workspace.p9710_mode_combo.setCurrentIndex(6)
    workspace.p9710_effective_period_spin.setValue(3.17)
    page = workspace.p9710_mode_stack.widget(6)
    next(b for b in page.findChildren(QPushButton) if b.text() == "Measure synchronized").click()
    assert workspace.p9710_last_e_effective_lx == 4.0
    assert workspace.p9710_last_i_effective_cd == 100.0  # 4 lx × (5 m)²
    assert "Above limit" in page.findChild(QProgressBar).format()


def test_effective_requires_manually_entered_period_before_any_read(workspace, monkeypatch):
    assert workspace.p9710_effective_period_spin.value() == 0.0
    def unexpected_worker(*args, **kwargs):
        pytest.fail('No device worker may start without a pulse period')
    monkeypatch.setattr(modes, 'EffectiveWorker', unexpected_worker)
    warnings = []
    monkeypatch.setattr(modes.QMessageBox, 'warning', lambda *args: warnings.append(args[-1]))
    workspace.p9710_meter_holder['meter'] = SimpleNamespace(is_connected=True)
    workspace.p9710_mode_combo.setCurrentIndex(6)
    page = workspace.p9710_mode_stack.widget(6)
    next(b for b in page.findChildren(QPushButton) if b.text() == 'Measure synchronized').click()
    assert len(warnings) == 1
    assert 'pulse period' in warnings[0]
    assert workspace.p9710_mode_worker_holder['worker'] is None


def test_new_effective_attempt_clears_old_range_and_results_before_worker(workspace, monkeypatch):
    page = workspace.p9710_mode_stack.widget(6)
    bar = page.findChild(QProgressBar)
    bar.setValue(17)
    workspace.p9710_last_e_effective_lx = 4.0
    workspace.p9710_last_i_effective_cd = 100.0
    workspace.p9710_last_reading = object()
    workspace.p9710_effective_period_spin.setValue(3.17)
    class WaitingWorker(ImmediateWorker):
        def start(self):
            assert not workspace.p9710_effective_period_spin.isEnabled()
            assert bar.value() == 0
            assert bar.format() == 'Unavailable'
            assert workspace.p9710_last_e_effective_lx is None
            assert workspace.p9710_last_i_effective_cd is None
            assert workspace.p9710_last_reading is None
            assert any(label.text() == 'E-effective: —' for label in page.findChildren(QLabel))
            self.finished.emit()
    monkeypatch.setattr(modes, 'EffectiveWorker', WaitingWorker)
    workspace.p9710_meter_holder['meter'] = SimpleNamespace(is_connected=True, reading=None)
    workspace.p9710_mode_combo.setCurrentIndex(6)
    next(b for b in page.findChildren(QPushButton) if b.text() == 'Measure synchronized').click()
    assert workspace.p9710_mode_worker_holder['worker'] is None
    assert workspace.p9710_effective_period_spin.value() == 3.17
    assert workspace.p9710_effective_period_spin.isEnabled()


def test_effective_advanced_settings_are_visible_and_can_be_collapsed(workspace, app):
    workspace.p9710_mode_combo.setCurrentIndex(6)
    workspace.resize(1366, 1000)
    workspace.show()
    app.processEvents()
    section = workspace.p9710_effective_advanced_section
    assert section.button.isChecked()
    assert section.content.isVisible()
    labels = [label.text() for label in section.content.findChildren(QLabel)]
    assert all(caption in labels for caption in (
        'Pre-trigger:', 'MI window:', 'Trigger threshold:', 'Schmidt-Clausen C:',
    ))
    assert all(spin.isVisible() for spin in section.content.findChildren(modes.QSpinBox))
    section.button.click()
    assert not section.content.isVisible()
    section.button.click()
    assert section.content.isVisible()


def test_instrument_scroll_is_independent_and_wheel_does_not_change_range(workspace, app):
    attach_luxmeter_workspace_tabs(workspace)
    attach_p9710_flash_timing_runtime(workspace)
    areas = attach_luxmeter_scroll_runtime(workspace)
    assert workspace.luxmeter_instrument_stack.count() == 2
    assert workspace.p9710_mode_stack.count() == 7
    workspace.resize(1366, 430)
    workspace.luxmeter_instrument_combo.setCurrentIndex(1)
    workspace.p9710_flash_timing_section.set_expanded(True)
    workspace.show()
    app.processEvents()
    scroll = areas[1]
    assert scroll.verticalScrollBar().maximum() > 100
    spin = next(s for s in workspace.p9710_mode_stack.widget(0).findChildren(QSpinBox)
                if s.maximum() == 7)
    original = spin.value()
    selector_position = workspace.luxmeter_instrument_combo.pos()
    event = QWheelEvent(QPointF(2, 2), QPointF(2, 2), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(spin, event)
    assert spin.value() == original
    assert scroll.verticalScrollBar().value() > 0
    retained = scroll.verticalScrollBar().value()
    workspace.luxmeter_instrument_combo.setCurrentIndex(0)
    app.processEvents()
    assert areas[0].verticalScrollBar().value() == 0
    workspace.luxmeter_instrument_combo.setCurrentIndex(1)
    app.processEvents()
    assert scroll.verticalScrollBar().value() == retained
    assert workspace.luxmeter_instrument_combo.pos() == selector_position
    assert workspace.luxmeter_instrument_combo.isVisible()


def test_continuous_stops_before_the_error_dialog_and_does_not_retry(workspace, monkeypatch, app):
    class FailedWorker(ImmediateWorker):
        def start(self):
            self.failed.emit("P-9710 rejected command 'SS0': ?1")
            self.finished.emit()
    monkeypatch.setattr(modes, 'CWWorker', FailedWorker)
    workspace.p9710_meter_holder['meter'] = SimpleNamespace(is_connected=True, reading=None)
    dialogs = []
    def dialog(*args):
        assert not any(timer.isActive() for timer in workspace.p9710_continuous_timers)
        dialogs.append(args[-1])
        app.processEvents()  # A modal dialog also processes timer events.
    monkeypatch.setattr(modes.QMessageBox, 'critical', dialog)
    page = workspace.p9710_mode_stack.widget(0)
    start = next(b for b in page.findChildren(QPushButton) if b.text() == 'Start continuous')
    start.click()
    for timer in workspace.p9710_continuous_timers:
        assert not timer.isActive()
    assert len(dialogs) == 1
    assert start.isEnabled()
    assert workspace.p9710_last_cw_reading is None
    assert any(label.text() == 'Continuous: stopped after read error' for label in page.findChildren(QLabel))


def test_disconnected_continuous_attempt_warns_once_and_stops(workspace, monkeypatch):
    dialogs = []
    monkeypatch.setattr(modes.QMessageBox, 'warning', lambda *args: dialogs.append(args[-1]))
    page = workspace.p9710_mode_stack.widget(0)
    next(b for b in page.findChildren(QPushButton) if b.text() == 'Start continuous').click()
    assert len(dialogs) == 1
    assert not any(timer.isActive() for timer in workspace.p9710_continuous_timers)


def test_continuous_keeps_polling_with_the_reported_gs7_60(workspace, monkeypatch):
    from PySide6.QtTest import QTest
    import p9710
    from test_p9710_protocol import ReplySerial

    monkeypatch.setattr(p9710.time, 'sleep', lambda seconds: None)
    meter = p9710.P9710('SIMULATED')
    meter.serial = ReplySerial({'SS0': b'?1\n', 'GS7': b'60\n', 'MV': b'12.3456\n',
                                'GA': b'24\n', 'GB': b'0\n', 'GD': b'24\n', 'GP': b'20\n'})
    class SnapshotWorker(ImmediateWorker):
        def __init__(self, meter, settings, parent=None):
            QObject.__init__(self, parent)
            self.reading = meter.read_cw_snapshot(**settings)
    monkeypatch.setattr(modes, 'CWWorker', SnapshotWorker)
    errors = []
    monkeypatch.setattr(modes.QMessageBox, 'critical', lambda *args: errors.append(args))
    workspace.p9710_meter_holder['meter'] = meter
    page = workspace.p9710_mode_stack.widget(0)
    interval = next(s for s in page.findChildren(modes.QDoubleSpinBox) if s.suffix() == ' s')
    interval.setValue(.05)
    next(b for b in page.findChildren(QPushButton) if b.text() == 'Start continuous').click()
    for _ in range(20):
        if meter.serial.sent.count('MV') >= 3:
            break
        QTest.qWait(50)
    assert workspace.p9710_continuous_timers[0].isActive()
    assert meter.serial.sent.count('MV') >= 3
    assert not errors
    assert workspace.p9710_last_cw_reading.cw_lx == 12.3456
    workspace.p9710_stop_continuous()


def test_cw_can_read_again_after_effective_fast_integration_is_rejected(workspace, monkeypatch):
    from PySide6.QtTest import QTest
    import p9710
    from test_p9710_protocol import ReplySerial

    monkeypatch.setattr(p9710.time, 'sleep', lambda seconds: None)
    meter = p9710.P9710('SIMULATED')
    meter.serial = ReplySerial({'SN1': b'?1\n', 'GS3': b'1000\n',
                                'MV': b'12.3456\n', 'GP': b'8.5\n'})
    class SynchronousCW(modes.CWWorker):
        def start(self):
            self.run()
            self.finished.emit()
    class SynchronousEffective(modes.EffectiveWorker):
        def start(self):
            self.run()
            self.finished.emit()
    monkeypatch.setattr(modes, 'CWWorker', SynchronousCW)
    monkeypatch.setattr(modes, 'EffectiveWorker', SynchronousEffective)
    errors = []
    monkeypatch.setattr(modes.QMessageBox, 'critical', lambda *args: errors.append(args[-1]))
    monkeypatch.setattr(modes, '_show_effective_error', lambda parent, message, details: errors.append(message))
    workspace.p9710_meter_holder['meter'] = meter
    cw_page = workspace.p9710_mode_stack.widget(0)
    integration = next(s for s in cw_page.findChildren(modes.QDoubleSpinBox) if s.suffix() == ' ms')
    integration.setValue(100.0)
    next(b for b in cw_page.findChildren(QPushButton) if b.text() == 'Read CW').click()
    assert workspace.p9710_last_cw_reading.cw_lx == 12.3456
    workspace.p9710_mode_combo.setCurrentIndex(6)
    workspace.p9710_effective_period_spin.setValue(3.17)
    effective_page = workspace.p9710_mode_stack.widget(6)
    next(b for b in effective_page.findChildren(QPushButton) if b.text() == 'Measure synchronized').click()
    assert len(errors) == 1 and 'GS3 returned' in errors[0]
    assert "SN1 -> '?1'" in workspace.p9710_last_effective_diagnostics
    assert "GS3 -> '1000'" in workspace.p9710_last_effective_diagnostics
    assert 'MI' not in meter.serial.sent
    assert workspace.p9710_mode_worker_holder['worker'] is None
    workspace.p9710_mode_combo.setCurrentIndex(0)
    next(b for b in cw_page.findChildren(QPushButton) if b.text() == 'Start continuous').click()
    for _ in range(20):
        if meter.serial.sent.count('MV') >= 3:
            break
        QTest.qWait(50)
    assert workspace.p9710_continuous_timers[0].isActive()
    assert meter.serial.sent.count('MV') >= 3
    assert len(errors) == 1
    workspace.p9710_stop_continuous()

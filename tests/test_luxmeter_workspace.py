import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QLabel, QProgressBar, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
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
    window.close()
    window.deleteLater()
    app.processEvents()


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
    page = workspace.p9710_mode_stack.widget(6)
    next(b for b in page.findChildren(QPushButton) if b.text() == "Measure synchronized").click()
    assert workspace.p9710_last_e_effective_lx == 4.0
    assert workspace.p9710_last_i_effective_cd == 100.0  # 4 lx × (5 m)²
    assert "Above limit" in page.findChild(QProgressBar).format()


def test_instrument_scroll_is_independent_and_wheel_does_not_change_range(workspace, app):
    attach_luxmeter_workspace_tabs(workspace)
    attach_p9710_flash_timing_runtime(workspace)
    areas = attach_luxmeter_scroll_runtime(workspace)
    assert workspace.luxmeter_subtabs.count() == 2
    assert workspace.p9710_mode_stack.count() == 7
    workspace.resize(1366, 430)
    workspace.luxmeter_subtabs.setCurrentIndex(1)
    workspace.p9710_flash_timing_section.set_expanded(True)
    workspace.show()
    app.processEvents()
    scroll = areas[1]
    assert scroll.verticalScrollBar().maximum() > 100
    spin = next(s for s in workspace.p9710_mode_stack.widget(0).findChildren(QSpinBox)
                if s.maximum() == 7)
    original = spin.value()
    tab_position = workspace.luxmeter_subtabs.tabBar().pos()
    event = QWheelEvent(QPointF(2, 2), QPointF(2, 2), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(spin, event)
    assert spin.value() == original
    assert scroll.verticalScrollBar().value() > 0
    retained = scroll.verticalScrollBar().value()
    workspace.luxmeter_subtabs.setCurrentIndex(0)
    app.processEvents()
    assert areas[0].verticalScrollBar().value() == 0
    workspace.luxmeter_subtabs.setCurrentIndex(1)
    app.processEvents()
    assert scroll.verticalScrollBar().value() == retained
    assert workspace.luxmeter_subtabs.tabBar().pos() == tab_position
    assert workspace.luxmeter_subtabs.tabBar().isVisible()


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
    QTest.qWait(180)
    assert workspace.p9710_continuous_timers[0].isActive()
    assert meter.serial.sent.count('MV') >= 3
    assert not errors
    assert workspace.p9710_last_cw_reading.cw_lx == 12.3456
    workspace.p9710_stop_continuous()

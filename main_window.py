from motion_controller import (
    MotionController,
    GAMMA,
    C_AXIS,
)

from machine_config import (
    JOG_STEP_DEG,
)

import serial


from PySide6.QtCore import (
    QTimer,
    Qt,
)

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QMessageBox,
)

from delta_modbus import (
    DeltaModbus,
    DeltaModbusError,
)

from machine_config import (
    PORT,
    APP_NAME,
    APP_VERSION,
    GAMMA_ID,
    C_ID,
    P0_01,
    P0_09,
    P0_17,
    P0_46,
    SON_BIT,
    GAMMA_PUU_PER_DEGREE,
    C_PUU_PER_DEGREE,
    GAMMA_SIGN,
    C_SIGN,
    REFRESH_INTERVAL_MS,
)


class AxisPanel(QGroupBox):

    def __init__(
        self,
        title: str,
    ):
        super().__init__(title)

        layout = QGridLayout()

        self.position_label = QLabel("—")
        self.angle_label = QLabel("—")
        self.alarm_label = QLabel("—")
        self.status_label = QLabel("—")
        self.son_label = QLabel("—")
        self.monitor_label = QLabel("—")

        self.jog_minus_button = QPushButton(
            "-0.1°"
        )

        self.jog_plus_button = QPushButton(
            "+0.1°"
        )

        layout.addWidget(
            QLabel("Feedback position:"),
            0,
            0,
        )
        layout.addWidget(
            self.position_label,
            0,
            1,
        )

        layout.addWidget(
            QLabel("Angle:"),
            1,
            0,
        )
        layout.addWidget(
            self.angle_label,
            1,
            1,
        )

        layout.addWidget(
            QLabel("Servo ON:"),
            2,
            0,
        )
        layout.addWidget(
            self.son_label,
            2,
            1,
        )

        layout.addWidget(
            QLabel("Alarm:"),
            3,
            0,
        )
        layout.addWidget(
            self.alarm_label,
            3,
            1,
        )

        layout.addWidget(
            QLabel("Status:"),
            4,
            0,
        )
        layout.addWidget(
            self.status_label,
            4,
            1,
        )

        layout.addWidget(
            QLabel("P0-17 monitor:"),
            5,
            0,
        )
        layout.addWidget(
            self.monitor_label,
            5,
            1,
        )

        layout.addWidget(
            self.jog_minus_button,
            6,
            0,
        )

        layout.addWidget(
            self.jog_plus_button,
            6,
            1,
        )

        self.setLayout(layout)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            f"{APP_NAME} {APP_VERSION}"
        )

        self.resize(
            900,
            520,
        )

        self.modbus = DeltaModbus(
            PORT
        )
        self.motion = MotionController(
            self.modbus
        )

        self.gamma_zero_puu = None
        self.c_zero_puu = None

        self.timer = QTimer(self)
        self.timer.setInterval(
            REFRESH_INTERVAL_MS
        )
        self.timer.timeout.connect(
            self.refresh_data
        )

        self.build_ui()
        self.apply_style()

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        central = QWidget()

        main_layout = QVBoxLayout(
            central
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header_layout = QHBoxLayout()

        title = QLabel(
            "LUMIGON"
        )

        title.setObjectName(
            "appTitle"
        )

        header_layout.addWidget(
            title
        )

        header_layout.addStretch()

        self.connection_label = QLabel(
            "● Disconnected"
        )

        self.connection_label.setObjectName(
            "connectionOff"
        )

        header_layout.addWidget(
            self.connection_label
        )

        main_layout.addLayout(
            header_layout
        )

        # ----------------------------------------------------
        # Connection controls
        # ----------------------------------------------------

        connection_box = QGroupBox(
            "Communication"
        )

        connection_layout = QHBoxLayout()

        connection_layout.addWidget(
            QLabel(
                f"Port: {PORT}"
            )
        )

        connection_layout.addWidget(
            QLabel(
                "38400 baud / 8N2 / Modbus RTU"
            )
        )

        connection_layout.addStretch()

        self.connect_button = QPushButton(
            "Connect"
        )

        self.disconnect_button = QPushButton(
            "Disconnect"
        )

        self.connect_button.clicked.connect(
            self.connect_drives
        )

        self.disconnect_button.clicked.connect(
            self.disconnect_drives
        )

        connection_layout.addWidget(
            self.connect_button
        )

        connection_layout.addWidget(
            self.disconnect_button
        )

        connection_box.setLayout(
            connection_layout
        )

        main_layout.addWidget(
            connection_box
        )

        # ----------------------------------------------------
        # Axis panels
        # ----------------------------------------------------

        axis_layout = QHBoxLayout()

        self.gamma_panel = AxisPanel(
            "Gamma Axis — S1"
        )

        self.c_panel = AxisPanel(
            "C Axis — S2"
        )

        axis_layout.addWidget(
            self.gamma_panel
        )

        axis_layout.addWidget(
            self.c_panel
        )

        main_layout.addLayout(
            axis_layout
        )
        self.gamma_panel.jog_minus_button.clicked.connect(
            lambda: self.jog_axis(
                GAMMA,
                -JOG_STEP_DEG,
            )
        )

        self.gamma_panel.jog_plus_button.clicked.connect(
            lambda: self.jog_axis(
                GAMMA,
                +JOG_STEP_DEG,
            )
        )

        self.c_panel.jog_minus_button.clicked.connect(
            lambda: self.jog_axis(
                C_AXIS,
                -JOG_STEP_DEG,
            )
        )

        self.c_panel.jog_plus_button.clicked.connect(
            lambda: self.jog_axis(
                C_AXIS,
                +JOG_STEP_DEG,
            )
        )
        # ----------------------------------------------------
        # Zero controls
        # ----------------------------------------------------

        zero_layout = QHBoxLayout()

        self.zero_button = QPushButton(
            "Capture Session Zero"
        )

        self.zero_button.clicked.connect(
            self.capture_session_zero
        )

        zero_layout.addWidget(
            self.zero_button
        )

        self.zero_info_label = QLabel(
            "Session zero not captured"
        )

        zero_layout.addWidget(
            self.zero_info_label
        )

        zero_layout.addStretch()

        main_layout.addLayout(
            zero_layout
        )

        # ----------------------------------------------------
        # Safety notice
        # ----------------------------------------------------

        notice = QLabel(
            "HMI v0.2 — Commissioning Mode — "
        "Only ±0.1° jog commands are permitted."
        )

        notice.setAlignment(
            Qt.AlignCenter
        )

        notice.setObjectName(
            "readOnlyNotice"
        )

        main_layout.addWidget(
            notice
        )

        self.setCentralWidget(
            central
        )

    # ========================================================
    # Styling
    # ========================================================

    def apply_style(self):

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #101820;
            }

            QWidget {
                color: #E8EEF3;
                font-family: Segoe UI;
                font-size: 10pt;
            }

            QGroupBox {
                border: 1px solid #34495E;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: 600;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }

            QPushButton {
                background-color: #1769AA;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #2185D0;
            }

            QPushButton:pressed {
                background-color: #0F568E;
            }

            QLabel#appTitle {
                font-size: 24pt;
                font-weight: 700;
                color: #4DA3FF;
            }

            QLabel#connectionOff {
                color: #FF7675;
                font-weight: 700;
            }

            QLabel#connectionOn {
                color: #55EFC4;
                font-weight: 700;
            }

            QLabel#readOnlyNotice {
                background-color: #17232D;
                border: 1px solid #34495E;
                border-radius: 6px;
                padding: 10px;
                color: #AAB7C4;
            }
            """
        )

    # ========================================================
    # Connection
    # ========================================================

    def connect_drives(self):

        try:
            self.modbus.connect()

            # Communication test
            self.modbus.read_u16(
                GAMMA_ID,
                P0_01,
            )

            self.modbus.read_u16(
                C_ID,
                P0_01,
            )

            self.connection_label.setText(
                "● Connected"
            )

            self.connection_label.setObjectName(
                "connectionOn"
            )

            self.connection_label.style().unpolish(
                self.connection_label
            )
            self.connection_label.style().polish(
                self.connection_label
            )

            self.refresh_data()

            self.timer.start()

        except Exception as exc:

            self.modbus.disconnect()

            QMessageBox.critical(
                self,
                "Connection Error",
                str(exc),
            )

    def disconnect_drives(self):

        self.timer.stop()

        self.modbus.disconnect()

        self.connection_label.setText(
            "● Disconnected"
        )

        self.connection_label.setObjectName(
            "connectionOff"
        )

        self.connection_label.style().unpolish(
            self.connection_label
        )
        self.connection_label.style().polish(
            self.connection_label
        )

    # ========================================================
    # Read Axis
    # ========================================================

    def read_axis(
        self,
        slave_id: int,
    ) -> dict:

        alarm = self.modbus.read_u16(
            slave_id,
            P0_01,
        )

        feedback = self.modbus.read_s32(
            slave_id,
            P0_09,
        )

        monitor = self.modbus.read_u16(
            slave_id,
            P0_17,
        )

        status = self.modbus.read_u16(
            slave_id,
            P0_46,
        )

        son = bool(
            status & SON_BIT
        )

        return {
            "alarm": alarm,
            "feedback": feedback,
            "monitor": monitor,
            "status": status,
            "son": son,
        }

    # ========================================================
    # Refresh
    # ========================================================

    def refresh_data(self):

        if not self.modbus.is_connected:
            return

        try:
            gamma = self.read_axis(
                GAMMA_ID
            )

            c_axis = self.read_axis(
                C_ID
            )

            self.update_axis_panel(
                panel=self.gamma_panel,
                data=gamma,
                zero_puu=self.gamma_zero_puu,
                puu_per_degree=(
                    GAMMA_PUU_PER_DEGREE
                ),
                sign=GAMMA_SIGN,
            )

            self.update_axis_panel(
                panel=self.c_panel,
                data=c_axis,
                zero_puu=self.c_zero_puu,
                puu_per_degree=(
                    C_PUU_PER_DEGREE
                ),
                sign=C_SIGN,
            )

        except (
            DeltaModbusError,
            serial.SerialException
        ) as exc:
            self.timer.stop()

            QMessageBox.critical(
                self,
                "Communication Error",
                str(exc),
            )

            self.disconnect_drives()

        except Exception as exc:
            self.timer.stop()

            QMessageBox.critical(
                self,
                "Unexpected Error",
                str(exc),
            )

    def update_axis_panel(
        self,
        panel: AxisPanel,
        data: dict,
        zero_puu,
        puu_per_degree: float,
        sign: int,
    ):

        feedback = data["feedback"]

        panel.position_label.setText(
            f"{feedback:+d} PUU"
        )

        if zero_puu is None:
            panel.angle_label.setText(
                "Zero not set"
            )
        else:
            delta_puu = (
                feedback
                - zero_puu
            )

            angle = (
                delta_puu
                / puu_per_degree
                / sign
            )

            panel.angle_label.setText(
                f"{angle:+.4f}°"
            )

        if data["son"]:
            panel.son_label.setText(
                "ON"
            )
        else:
            panel.son_label.setText(
                "OFF"
            )

        panel.alarm_label.setText(
            f"0x{data['alarm']:04X}"
        )

        panel.status_label.setText(
            f"0x{data['status']:04X}"
        )

        monitor = data["monitor"]

        if monitor == 0:
            panel.monitor_label.setText(
                "0 — Feedback Position"
            )
        else:
            panel.monitor_label.setText(
                f"{monitor} — WARNING"
            )

    # ========================================================
    # Session Zero
    # ========================================================

    def capture_session_zero(self):

        if not self.modbus.is_connected:
            QMessageBox.warning(
                self,
                "Not Connected",
                "Connect to both drives first.",
            )
            return

        try:
            self.gamma_zero_puu = (
                self.modbus.read_s32(
                    GAMMA_ID,
                    P0_09,
                )
            )

            self.c_zero_puu = (
                self.modbus.read_s32(
                    C_ID,
                    P0_09,
                )
            )

            self.zero_info_label.setText(
                "Session zero: "
                f"Gamma={self.gamma_zero_puu:+d} PUU, "
                f"C={self.c_zero_puu:+d} PUU"
            )

            self.motion.set_session_zero(
                self.gamma_zero_puu,
                self.c_zero_puu,
            )

            self.refresh_data()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Zero Capture Error",
                str(exc),
            )

    def jog_axis(
            self,
            axis,
            delta_degree,
    ):

        if not self.modbus.is_connected:
            QMessageBox.warning(
                self,
                "Not Connected",
                "Connect to the drives first.",
            )
            return

        if (
                self.gamma_zero_puu is None
                or self.c_zero_puu is None
        ):
            QMessageBox.warning(
                self,
                "Session Zero Required",
                "Capture Session Zero before movement.",
            )
            return

        direction = (
            "+"
            if delta_degree > 0
            else "-"
        )

        answer = QMessageBox.question(
            self,
            "Confirm Limited Jog",
            f"{axis.name}: move "
            f"{direction}0.1°?\n\n"
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.timer.stop()

        try:
            self.motion.jog(
                axis,
                delta_degree,
            )

            QTimer.singleShot(
                500,
                self.refresh_data,
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Movement Blocked",
                str(exc),
            )

        finally:
            self.timer.start()

    # ========================================================
    # Close
    # ========================================================

    def closeEvent(
        self,
        event,
    ):

        self.timer.stop()
        self.modbus.disconnect()

        event.accept()
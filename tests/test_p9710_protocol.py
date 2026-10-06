import pytest

import p9710
from p9710 import P9710, P9710Error


class ReplySerial:
    is_open = True
    timeout = 3.0

    def __init__(self, replies):
        self.replies = replies
        self.sent = []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.sent.append(data.decode().strip())

    def flush(self):
        pass

    def readline(self):
        return self.replies.get(self.sent[-1], b'\n')


@pytest.fixture
def make_meter(monkeypatch):
    monkeypatch.setattr(p9710.time, 'sleep', lambda seconds: None)
    def make(**replies):
        meter = P9710('SIMULATED')
        meter.serial = ReplySerial({'GR': b'5\n', 'GS0': b'0\n', 'GS3': b'1\n', **replies})
        return meter
    return make


@pytest.mark.parametrize('reply', [b'?2\n', b'?16\n', b'*\n'])
def test_configuration_command_error_is_not_silently_discarded(make_meter, reply):
    meter = make_meter(SR5=reply)
    with pytest.raises(P9710Error, match='rejected command'):
        meter.configure_cw(integration_ms=.1, range_id=5, verify=True)
    assert meter.serial.sent == ['SB0', 'SR5']


@pytest.mark.parametrize('command, reply', [('GR', b'4\n'), ('GS0', b'1\n'), ('GS3', b'1000\n'), ('GR', b'nan\n'), ('GR', b'?2\n')])
def test_measurement_requires_actual_range_autorange_and_integration_readback(make_meter, command, reply):
    meter = make_meter(**{command: reply})
    with pytest.raises(P9710Error):
        meter.configure_cw(integration_ms=.1, range_id=5, verify=True)


def test_matching_readbacks_are_required_in_order(make_meter):
    meter = make_meter()
    meter.configure_cw(integration_ms=.1, range_id=5, verify=True)
    assert meter.serial.sent == ['SB0', 'SR5', 'SN1', 'SS0', 'GR', 'GS0', 'GS3']


def test_raw_command_error_is_traced_before_raising(make_meter):
    meter = make_meter(SR5=b'?2\n')
    trace = []
    meter.trace_callback = lambda *args: trace.append(args)
    with pytest.raises(P9710Error):
        meter.command('SR5')
    assert trace[0][:2] == ('SR5', '?2')


def test_gp_value_is_not_rescaled_and_its_literal_reply_is_traced(make_meter):
    meter = make_meter(GP=b'+2.50E-01\n')
    trace = []
    meter.trace_callback = lambda *args: trace.append(args)
    assert meter.read_range_utilization() == .25
    assert trace[0][:2] == ('GP', '+2.50E-01')


def test_missing_gp_is_logged_and_rejected(make_meter):
    meter = make_meter(GP=b'')
    trace = []
    meter.trace_callback = lambda *args: trace.append(args)
    with pytest.raises(P9710Error, match='No response'):
        meter.read_range_utilization()
    assert trace[0][:2] == ('GP', '<NO RESPONSE>')

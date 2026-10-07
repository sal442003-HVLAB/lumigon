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


@pytest.mark.parametrize('flags', [0, 1, 4, 60, 128, 253])
def test_rejected_ss0_is_allowed_only_when_readback_proves_sync_already_off(make_meter, flags):
    meter = make_meter(SS0=b'?1\n', GS7=f'{flags}\n'.encode())
    meter.configure_cw(integration_ms=.1, range_id=5, verify=True)
    assert meter.serial.sent == ['SB0', 'SR5', 'SN1', 'SS0', 'GS7', 'GR', 'GS0', 'GS3']


@pytest.mark.parametrize('reply', [b'2\n', b'3\n', b'62\n', b'255\n',
                                   b'-1\n', b'256\n', b'60.5\n', b'?1\n', b'', b'nan\n'])
def test_rejected_ss0_must_not_be_ignored_with_unknown_or_active_sync(make_meter, reply):
    meter = make_meter(SS0=b'?1\n', GS7=reply)
    with pytest.raises(P9710Error, match='Synchronisation OFF'):
        meter.configure_cw(integration_ms=.1, range_id=5)


def test_reported_gs7_60_allows_repeated_cw_snapshots(make_meter):
    meter = make_meter(SS0=b'?1\n', GS7=b'60\n', MV=b'12.3456\n',
                       GA=b'24\n', GB=b'0\n', GD=b'24\n', GP=b'20\n')
    for _ in range(3):
        reading = meter.read_cw_snapshot(integration_ms=.1, range_id=5, sync_enabled=False)
        assert reading.cw_lx == 12.3456
        assert reading.range_utilization_pct == 20.0
        assert reading.sync_enabled is False
    assert meter.serial.sent.count('MV') == 3


def test_other_ss_errors_and_enabling_sync_are_never_silently_ignored(make_meter):
    meter = make_meter(SS0=b'?16\n', GS7=b'0\n')
    with pytest.raises(P9710Error, match='SS0'):
        meter.configure_cw(integration_ms=.1)
    assert 'GS7' not in meter.serial.sent
    meter = make_meter(SS1=b'?1\n', GS7=b'0\n')
    with pytest.raises(P9710Error, match='SS1'):
        meter.configure_cw(integration_ms=.1, sync_enabled=True)


@pytest.mark.parametrize('milliseconds,ticks', [(100, 10), (600, 60), (10000, 1000)])
def test_effective_window_is_sent_in_10ms_device_ticks(make_meter, milliseconds, ticks):
    meter = make_meter()
    meter.configure_effective(window_ms=milliseconds)
    assert f'SM{ticks}' in meter.serial.sent


@pytest.mark.parametrize('milliseconds', [0, 10, 99, 601, 200000])
def test_invalid_effective_window_is_rejected_before_any_commands(make_meter, milliseconds):
    meter = make_meter()
    with pytest.raises(ValueError, match='10 ms steps'):
        meter.configure_effective(window_ms=milliseconds)
    assert meter.serial.sent == []


def test_effective_trigger_has_a_finite_default_timeout(make_meter, monkeypatch):
    meter = make_meter()
    monkeypatch.setattr(meter, 'configure_flash_detection', lambda **kwargs: None)
    def trigger(**kwargs):
        assert kwargs['timeout_s'] == 8.0
        raise P9710Error('No reference flash')
    monkeypatch.setattr(meter, 'detect_reference_flash', trigger)
    with pytest.raises(P9710Error, match='No reference flash'):
        meter.synchronized_effective(period_s=3.17, pretrigger_ms=100, window_ms=600)


def test_effective_reply_wait_matches_the_actual_device_window(make_meter, monkeypatch):
    meter = make_meter(GP=b'20\n')
    monkeypatch.setattr(meter, 'configure_flash_detection', lambda **kwargs: None)
    monkeypatch.setattr(meter, 'detect_reference_flash', lambda **kwargs: (10.0, 8.0))
    monkeypatch.setattr(meter, '_wait_until', lambda target: None)
    original_query = meter.query
    def query(command, **kwargs):
        if command == 'MI':
            assert 'SM60' in meter.serial.sent
            assert kwargs['wait_s'] == pytest.approx(.65)
            assert kwargs['timeout_s'] == pytest.approx(2.6)
            return '4.0'
        return original_query(command, **kwargs)
    monkeypatch.setattr(meter, 'query', query)
    result = meter.synchronized_effective(period_s=3.17, pretrigger_ms=100, window_ms=600)
    assert result.window_ms == 600
    assert result.e_effective_lx == 4.0


def test_rejected_sn1_can_use_only_the_confirmed_required_integration(make_meter):
    meter = make_meter(SN1=b'?1\n', SS0=b'?1\n', GS7=b'60\n')
    meter.configure_flash_detection(range_id=5)
    assert meter.serial.sent == ['SB0', 'SR5', 'SN1', 'GS3', 'SS0', 'GS7', 'GR', 'GS0', 'GS3']


@pytest.mark.parametrize('reply', [b'1000\n', b'0\n', b'1.5\n', b'nan\n',
                                   b'inf\n', b'?1\n', b'', b'invalid 1\n'])
def test_rejected_sn1_with_wrong_or_unknown_integration_blocks_flash_acquisition(make_meter, reply):
    meter = make_meter(SN1=b'?1\n', GS3=reply)
    with pytest.raises(P9710Error, match='CW integration|GS3 returned') as error:
        meter.synchronized_effective(period_s=3.17, pretrigger_ms=100, window_ms=600)
    assert "verify the meter's CW" in str(error.value)
    assert '0.1 ms' in str(error.value)
    assert meter.serial.sent == ['SB0', 'SR5', 'SN1', 'GS3']


@pytest.mark.parametrize('reply', [b'?2\n', b'?16\n', b'*\n'])
def test_other_integration_command_errors_are_not_bypassed(make_meter, reply):
    meter = make_meter(SN1=reply)
    with pytest.raises(P9710Error, match='SN1'):
        meter.configure_flash_detection()
    assert 'GS3' not in meter.serial.sent


def test_flash_setup_checks_integration_even_after_an_accepted_setter(make_meter):
    meter = make_meter(GS3=b'1000\n')
    with pytest.raises(P9710Error, match='configuration mismatch: GS3'):
        meter.synchronized_effective(period_s=3.17, pretrigger_ms=100, window_ms=600)
    assert 'MV' not in meter.serial.sent
    assert 'MI' not in meter.serial.sent


def test_full_effective_path_with_rejected_sn1_and_confirmed_readback(make_meter, monkeypatch):
    meter = make_meter(SN1=b'?1\n', SS0=b'?1\n', GS7=b'60\n',
                       MV=b'8\n', MI=b'4\n', GP=b'20\n')
    monkeypatch.setattr(meter, '_wait_until', lambda target: None)
    reading = meter.synchronized_effective(period_s=3.17, pretrigger_ms=100, window_ms=600)
    assert reading.e_effective_lx == 4.0
    assert reading.trigger_sample_lx == 8.0
    assert reading.range_utilization_pct == 20.0
    assert meter.serial.sent == ['SB0', 'SR5', 'SN1', 'GS3', 'SS0', 'GS7',
                                'GR', 'GS0', 'GS3', 'MV', 'SB0', 'SR5',
                                'SU0.2', 'SM60', 'SZ0', 'MI', 'GP']


@pytest.mark.parametrize('command', ['SS0', 'SN1', 'SU0.2', 'SM60'])
def test_setters_wait_for_delayed_complete_acknowledgements(make_meter, command):
    meter = make_meter()
    class DelayedSerial(ReplySerial):
        def readline(self):
            # Model a device reply arriving after 200 ms. The previous 50 ms
            # command timeout returned b'', which was accepted as success.
            assert self.timeout == 3.0
            return b'\n' if self.timeout >= .2 else b''
    meter.serial = DelayedSerial({})
    meter.command(command)
    assert meter.serial.sent == [command]
    assert meter.serial.timeout == 3.0


def test_delayed_rejection_stays_with_its_own_command_not_the_next_setter(make_meter):
    meter = make_meter()
    class DelayedErrorSerial(ReplySerial):
        def readline(self):
            return b'?1\n' if self.timeout >= .2 else b''
    meter.serial = DelayedErrorSerial({})
    with pytest.raises(p9710.P9710CommandError) as error:
        meter.configure_effective(window_ms=600)
    assert error.value.command == 'SB0'
    assert meter.serial.sent == ['SB0']


@pytest.mark.parametrize('reply', [b'', b'?1', b'\r'])
def test_absent_or_partial_setter_reply_is_never_an_ack_and_blocks_next_send(make_meter, reply):
    meter = make_meter(**{'SU0.2': reply})
    with pytest.raises(P9710Error, match='LF acknowledgement'):
        meter.configure_effective(window_ms=600)
    assert meter.serial.sent == ['SB0', 'SR5', 'SU0.2']
    with pytest.raises(P9710Error, match='disconnect and reconnect'):
        meter.command('SM60')
    assert meter.serial.sent == ['SB0', 'SR5', 'SU0.2']
    assert meter.serial.timeout == 3.0


@pytest.mark.parametrize('reply', [b'\n', b'\r\n', b'#\n'])
def test_complete_empty_or_hash_ack_is_accepted(make_meter, reply):
    meter = make_meter(**{'SU0.2': reply})
    meter.command('SU0.2')
    meter.command('SM60')
    assert meter.serial.sent == ['SU0.2', 'SM60']


@pytest.mark.parametrize('command', ['SU0.2', 'SM60'])
def test_genuine_effective_setting_rejection_still_blocks_mi(make_meter, command):
    meter = make_meter(**{command: b'?1\n'})
    with pytest.raises(p9710.P9710CommandError) as error:
        meter.configure_effective(window_ms=600)
    assert error.value.command == command
    assert 'MI' not in meter.serial.sent


def test_partial_query_cannot_be_used_as_a_measurement_or_shift_to_gp(make_meter):
    meter = make_meter(MV=b'12.34')
    with pytest.raises(P9710Error, match='LF acknowledgement'):
        meter.read_mv(attempts=1)
    with pytest.raises(P9710Error, match='framing is uncertain'):
        meter.read_range_utilization()
    assert meter.serial.sent == ['MV']


def test_query_uses_its_requested_timeout_and_restores_serial_timeout(make_meter):
    meter = make_meter(MI=b'4.0\n')
    meter.serial.timeout = 1.5
    original = meter.serial.readline
    def readline():
        assert meter.serial.timeout == 2.6
        return original()
    meter.serial.readline = readline
    assert meter.query('MI', timeout_s=2.6) == '4.0'
    assert meter.serial.timeout == 1.5

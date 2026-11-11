"""Interaction tests use the actual popup widgets; no device commands are connected."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from aircon.device import state_from_resources
from app.panel import ControlPanel, popup_position
from shared.ui import BG, MUTED, SUBTLE


def test_lamp_slider_release_sends_immediately(panel):
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    page = panel.lamp_page; requests = []
    page.commandRequested.connect(lambda *args: requests.append(args))
    page.level.setSliderDown(True); page.level.setValue(70)
    assert requests == []
    page.level.setSliderDown(False)
    assert requests == [('level', 70)]
    assert page.state.level == 60


def test_lamp_keyboard_burst_sends_latest_value_within_200ms(panel):
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    page = panel.lamp_page; requests = []
    page.commandRequested.connect(lambda *args: requests.append(args))
    for value in (65, 70, 75): page.level.setValue(value)
    QTest.qWait(200)
    assert requests == [('level', 75)] and page.state.level == 60


@pytest.fixture(scope='module')
def application():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
    app.setStyle('Fusion')
    return app


@pytest.fixture
def panel(application):
    state = state_from_resources(json.loads((Path(__file__).parent/'fixtures/ar12-controls.json').read_text()))
    state.power = True; state.display_light = True
    widget = ControlPanel(); widget.resize(388, 650)
    widget.render(state, True, False, 'Estado confirmado', {'reduce_motion': True})
    widget.show(); application.processEvents()
    yield widget
    widget.pending_temperature = None; widget.hide(); widget.deleteLater(); application.processEvents()


def test_toggle_waits_for_hardware_confirmation(panel):
    requests = []
    panel.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    QTest.mouseClick(panel.light_toggle, Qt.MouseButton.LeftButton)
    assert requests == [('display_light', False)]
    assert panel.light_toggle.isChecked() is True
    assert panel.light_toggle.position == 1.


def test_temperature_burst_sends_one_final_value(panel):
    requests = []
    panel.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    for _ in range(3): QTest.mouseClick(panel.plus, Qt.MouseButton.LeftButton)
    assert panel.readout.value == 27
    assert requests == []
    QTest.qWait(470)
    assert requests == [('temperature', 27)]


def test_pending_adjustment_is_committed_when_popup_closes(panel):
    requests = []
    panel.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    QTest.mouseClick(panel.plus, Qt.MouseButton.LeftButton)
    panel.hide()
    assert requests == [('temperature', 25)]


def test_power_off_keeps_light_available(panel):
    panel.state.power = False
    panel.render(panel.state, True, False, 'Estado confirmado', {'reduce_motion': True})
    assert panel.light_toggle.isEnabled()
    assert not panel.slider.isEnabled()
    assert not panel.wind_toggle.isEnabled()


def test_readback_after_failure_reverts_proposed_temperature(panel):
    panel.slider.setValue(9)
    panel.commit_temperature()
    assert panel.readout.value == 25
    panel.render(panel.state, True, False, 'O aparelho não confirmou o ajuste.', {'reduce_motion': True}, error=True)
    assert panel.readout.value == 24
    assert 'não confirmou' in panel.status.text()


def test_pending_temperature_remains_visible_until_readback(panel):
    panel.slider.setValue(9)
    panel.commit_temperature()
    panel.render(panel.state, True, True, 'Comando recebido · conferindo estado…', {'reduce_motion': True}, operation='command')
    assert panel.readout.value == 25
    assert panel.state.temperature == 24
    assert 'conferindo' in panel.status.text()
    panel.state.temperature = 25
    panel.render(panel.state, True, False, 'Confirmado', {'reduce_motion': True})
    assert panel.readout.value == 25
    assert panel.sent_temperature is None


def test_reduced_motion_and_hidden_panel_stop_airflow(panel):
    assert not panel.appliance.timer.isActive()
    panel.reduced = False; panel.appliance.reduced = False; panel.appliance.sync_timer()
    assert panel.appliance.timer.isActive()
    panel.hide()
    assert not panel.appliance.timer.isActive()


def test_refresh_and_search_buttons_emit_actions(panel):
    actions = []
    panel.refreshRequested.connect(lambda: actions.append('refresh'))
    panel.searchRequested.connect(lambda: actions.append('search'))
    QTest.mouseClick(panel.refresh_button, Qt.MouseButton.LeftButton)
    panel.show_page(1)
    QTest.mouseClick(panel.search_button, Qt.MouseButton.LeftButton)
    assert actions == ['refresh', 'search']


def test_invalid_manual_ip_does_not_request_connection(panel):
    requests = []
    panel.connectRequested.connect(requests.append)
    panel.show_page(1); panel.ip_field.setText('samsung.com')
    QTest.mouseClick(panel.connect_button, Qt.MouseButton.LeftButton)
    assert requests == []
    assert 'IP válido' in panel.settings_status.text()


def test_offline_state_stops_airflow_and_disables_commands(panel):
    panel.render(panel.state, False, False, 'Sem conexão', {'reduce_motion': False}, error=True)
    assert not panel.appliance.timer.isActive()
    assert not panel.power_button.isEnabled()
    assert not panel.light_toggle.isEnabled()
    assert 'última leitura' in panel.room_label.text()


def test_keyboard_escape_returns_and_closes(panel):
    panel.show_page(1)
    QTest.keyClick(panel.ip_field, Qt.Key.Key_Escape)
    assert panel.pages.currentIndex() == 0
    QTest.keyClick(panel.power_button, Qt.Key.Key_Escape)
    assert not panel.isVisible()


def test_keyboard_enter_activates_light_toggle(panel):
    requests = []
    panel.commandRequested.connect(lambda kind, value: requests.append((kind,value)))
    QTest.keyClick(panel.light_toggle, Qt.Key.Key_Return)
    assert requests == [('display_light',False)]
    assert panel.light_toggle.isChecked()


def test_temperature_is_sent_immediately_when_slider_is_released(panel):
    requests = []
    panel.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    panel.slider.setValue(panel.slider.value()+1)
    panel.slider.sliderReleased.emit()
    QTest.qWait(20)
    assert requests == [('temperature', 25)]


def test_repeated_readback_does_not_restart_the_same_toggle_animation(panel):
    toggle = panel.light_toggle; toggle.reduced = False
    toggle.confirm(False)
    animation = toggle._animations['position']
    animation.setCurrentTime(80)
    position = toggle.position
    toggle.confirm(False)
    assert toggle._animations['position'] is animation
    assert toggle.position == position and animation.currentTime() == 80


@pytest.mark.parametrize('area,anchor', [(QRect(0,0,1920,1040),QRect(1810,1041,20,20)),
                                       (QRect(-1920,0,1920,1040),QRect(-50,1041,20,20)),
                                       (QRect(0,0,800,600),QRect(0,0,20,20))])
def test_popup_stays_on_screen(area, anchor):
    position = popup_position(anchor, area, 388, min(650, area.height()-24))
    geometry = QRect(position.x(), position.y(),388,min(650,area.height()-24))
    assert area.contains(geometry)
    assert geometry.right() == area.right()
    assert geometry.bottom() == area.bottom()


def test_popup_overflow_icon_does_not_change_bottom_right_alignment():
    area = QRect(-1920, -180, 1920, 1040)
    anchors = (QRect(-240, 500, 24, 24), QRect(-60, 862, 24, 24))
    assert popup_position(anchors[0], area, 388, 650) == popup_position(anchors[1], area, 388, 650)


def test_secondary_text_contrast():
    def luminance(color):
        def linear(channel):
            c=channel/255
            return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
        r,g,b,_=color.getRgb()
        return .2126*linear(r)+.7152*linear(g)+.0722*linear(b)
    for foreground in (MUTED, SUBTLE):
        assert (luminance(foreground)+.05)/(luminance(BG)+.05)>=4.5


def lamp_state():
    from lamp.smartthings import LampState
    return LampState(power=True, level=60, kelvin=3000, hue=60, saturation=100,
                     capabilities=frozenset({'switch', 'switchLevel', 'colorTemperature', 'colorControl'}))


def test_device_selector_changes_page_without_sending_commands(panel):
    requests = []
    panel.commandRequested.connect(lambda *args: requests.append(args))
    panel.lamp_page.commandRequested.connect(lambda *args: requests.append(args))
    QTest.mouseClick(panel.devices.buttons[1], Qt.MouseButton.LeftButton)
    assert panel.pages.currentIndex() == 2 and panel.active_device == 'lamp'
    assert not panel.lamp_page.power.isEnabled()
    assert not panel.lamp_page.level.isEnabled()
    assert requests == []
    QTest.mouseClick(panel.devices.buttons[0], Qt.MouseButton.LeftButton)
    assert panel.pages.currentIndex() == 0


def test_lamp_slider_burst_debounces_and_waits_for_confirmation(panel):
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    panel.select_device('lamp')
    requests = []; page = panel.lamp_page
    page.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    for value in (61, 70, 80): page.level.setValue(value)
    assert requests == [] and 'ajuste' in page.level_value.text()
    QTest.qWait(470)
    assert requests == [('level', 80)]
    panel.render_lamp(lamp_state(), True, True, 'Enviando', {}, True, operation='command')
    assert page.level.value() == 80 and page.state.level == 60
    panel.render_lamp(lamp_state(), True, False, 'Não confirmado', {}, True, error=True)
    assert page.level.value() == 60 and 'ajuste' not in page.level_value.text()


def test_lamp_color_converts_degrees_to_smartthings_percentage(panel):
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    panel.select_device('lamp')
    requests = []; page = panel.lamp_page
    page.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    page.hue.setValue(180); page.saturation.setValue(80); page.commit()
    assert requests == [('color', {'hue': 50, 'saturation': 80})]


def test_switching_devices_commits_only_explicit_lamp_adjustment(panel):
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    panel.select_device('lamp')
    requests = []; panel.lamp_page.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    panel.lamp_page.kelvin.setValue(4200); panel.select_device('ac')
    assert requests == [('kelvin', 4200)]
    assert panel.pages.currentIndex() == 0


def test_lamp_off_and_unsupported_capabilities_disable_adjustments(panel):
    state = lamp_state(); state.power = False
    state.capabilities = frozenset({'switch', 'switchLevel'})
    panel.render_lamp(state, True, False, 'Confirmado', {}, True)
    panel.select_device('lamp')
    assert panel.lamp_page.power.isEnabled() and not panel.lamp_page.level.isEnabled()
    assert panel.lamp_page.white_section.isHidden() and panel.lamp_page.color_section.isHidden()


def test_lamp_setup_masks_clears_token_and_never_selects_first_lamp(panel):
    from PySide6.QtWidgets import QLineEdit
    panel.select_device('lamp'); panel.show_page(3)
    assert panel.lamp_setup.token.echoMode() == QLineEdit.EchoMode.Password
    tokens = []; panel.lamp_setup.authorizeRequested.connect(tokens.append)
    panel.lamp_setup.token.setText('fixture-token'); panel.lamp_setup.submit()
    assert tokens == ['fixture-token'] and panel.lamp_setup.token.text() == ''
    found = [{'device_id': 'first', 'component': 'main', 'name': 'Lâmpada 1'}]
    panel.lamp_setup.set_found(found)
    assert panel.lamp_setup.found.currentData() is None
    QTest.keyClick(panel.lamp_setup.token, Qt.Key.Key_Escape)
    assert panel.pages.currentIndex() == 2
    QTest.keyClick(panel.lamp_page.connect_button, Qt.Key.Key_Escape)
    assert not panel.isVisible()


def test_reduce_motion_applies_to_lamp_scene(panel):
    panel.select_device('lamp')
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    assert panel.lamp_page.scene.reduced is True
    assert panel.lamp_page.scene.illumination == .6


def test_retained_readings_outside_slider_range_are_not_misrepresented(panel):
    state = lamp_state(); state.power = False; state.level = 0
    state.kelvin = 1800
    panel.render_lamp(state, True, False, 'Confirmado', {}, True)
    assert panel.lamp_page.level_value.text() == '0%'
    assert panel.lamp_page.kelvin_value.text() == '1800 K'


def test_hidden_settings_do_not_force_control_page_scroll(panel):
    panel.select_device('ac'); QApplication.processEvents()
    assert panel.scroll.verticalScrollBar().maximum() == 0


def test_local_connection_masks_key_and_preserves_selected_identity(panel):
    from PySide6.QtWidgets import QLineEdit
    setup = panel.lamp_local_setup
    info = {'provider': 'local', 'device_id': 'fixturelamp', 'host': '192.168.15.11', 'version': 3.5, 'name': 'Dispositivo Tuya'}
    setup.set_found([info]); panel.select_device('lamp'); panel.show_page(4)
    assert setup.key.echoMode() == QLineEdit.EchoMode.Password
    requests = []; setup.connectRequested.connect(lambda i, key: requests.append((i, key)))
    setup.key.setText('short'); setup.submit(); assert requests == []
    setup.key.setText('fixturelocalkey1'); setup.submit()
    assert requests == [(info, 'fixturelocalkey1')] and setup.key.text() == ''
    QTest.keyClick(setup.search, Qt.Key.Key_Escape)
    assert panel.pages.currentIndex() == 2


def test_saved_lamp_settings_hide_commissioning_and_remain_above_taskbar(panel):
    info = {'provider': 'local', 'device_id': 'fixturelamp', 'host': '192.168.15.11', 'version': 3.5, 'name': 'Lâmpada 12W'}
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', info, True)
    panel.select_device('lamp'); panel.show_page(4)
    setup = panel.lamp_local_setup
    assert setup.summary.isVisible() and not setup.form.isVisible()
    assert not setup.key.isVisible() and not setup.cloud.isVisible()
    assert not setup.retry.isVisible()
    assert setup.device_name.text() == 'Lâmpada 12W' and 'Conectada' in setup.connection_reading.text()
    available = panel.screen().availableGeometry()
    assert panel.geometry().bottom() == available.bottom()
    assert panel.geometry().right() == available.right()
    assert panel.height() == min(340, available.height()-24)


def test_connection_editor_and_advanced_options_are_explicit_and_reset_on_return(panel):
    info = {'provider': 'local', 'device_id': 'fixturelamp', 'host': '192.168.15.11', 'version': 3.5, 'name': 'Lâmpada'}
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', info, True)
    panel.select_device('lamp'); panel.show_page(4); setup = panel.lamp_local_setup
    QTest.mouseClick(setup.change, Qt.MouseButton.LeftButton)
    assert setup.key.isVisible() and not setup.cloud.isVisible()
    setup.key.setText('fixturelocalkey1')
    QTest.mouseClick(setup.more, Qt.MouseButton.LeftButton)
    assert setup.cloud.isVisible() and setup.import_button.isVisible()
    panel.show_page(2); panel.show_page(4)
    assert setup.key.text() == '' and not setup.form.isVisible() and not setup.advanced.isVisible()
    panel.show_page(2)
    assert panel.height() == min(650, panel.screen().availableGeometry().height()-24)


def test_offline_saved_lamp_reconnects_without_requesting_key(panel):
    info = {'provider': 'local', 'device_id': 'fixturelamp', 'name': 'Lâmpada'}
    panel.render_lamp(lamp_state(), False, False, 'Tentando reconectar', info, True, error=True)
    panel.select_device('lamp'); panel.show_page(4); setup = panel.lamp_local_setup
    requests = []; setup.reconnectRequested.connect(lambda: requests.append(True))
    assert setup.retry.isVisible() and not setup.key.isVisible()
    QTest.mouseClick(setup.retry, Qt.MouseButton.LeftButton)
    assert requests == [True]


def test_removing_lamp_requires_explicit_confirmation(panel):
    info = {'provider': 'local', 'device_id': 'fixturelamp', 'name': 'Lâmpada'}
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', info, True)
    panel.select_device('lamp'); panel.show_page(4); setup = panel.lamp_local_setup
    requests = []; setup.disconnectRequested.connect(lambda: requests.append(True))
    setup.edit(); setup.more.setChecked(True)
    QTest.mouseClick(setup.disconnect, Qt.MouseButton.LeftButton)
    assert setup.forget_confirmation.isVisible() and requests == []
    QTest.mouseClick(setup.confirm_forget, Qt.MouseButton.LeftButton)
    assert requests == [True]


def test_local_white_control_uses_percentage_not_guessed_kelvin(panel):
    state = lamp_state(); state.white_unit = '%'; state.kelvin = 20; state.minimum_kelvin = 0; state.maximum_kelvin = 100
    panel.render_lamp(state, True, False, 'Confirmado', {'provider': 'local'}, True)
    assert panel.lamp_page.kelvin_value.text() == '20%'
    assert panel.lamp_page.kelvin.maximum() == 100 and panel.lamp_page.kelvin.singleStep() == 1
    panel.render_lamp(lamp_state(), True, False, 'Confirmado', {}, True)
    panel.select_device('lamp'); QApplication.processEvents()
    assert panel.scroll.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize('unit,expected', [('%', [0, 29, 100]), ('K', [3000, 4000, 6500])])
def test_white_presets_send_native_temperature_and_wait_for_confirmation(panel, unit, expected):
    state = lamp_state(); state.white_unit = unit; state.color_mode = 'white'
    state.kelvin = 20 if unit == '%' else 4200
    state.minimum_kelvin = 0 if unit == '%' else 2000
    state.maximum_kelvin = 100 if unit == '%' else 6500
    panel.render_lamp(state, True, False, 'Confirmado', {'provider': 'local' if unit == '%' else 'smartthings'}, True)
    panel.select_device('lamp'); page = panel.lamp_page
    requests = []; page.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    for button, target, code in zip(page.white_presets.buttons, expected, page.white_presets.codes):
        state.kelvin = 20 if unit == '%' else 4200
        panel.render_lamp(state, True, False, 'Confirmado', {}, True)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert requests[-1] == ('kelvin', target)
        assert page.white_presets.current == -1
        assert state.kelvin != target and state.level == 60
        panel.render_lamp(state, True, True, 'Enviando', {}, True, operation='command')
        assert not button.isEnabled()
        state.kelvin = target
        panel.render_lamp(state, True, False, 'Confirmado', {}, True)
        assert page.white_presets.codes[page.white_presets.current] == code
        assert 'ajuste' not in page.kelvin_value.text()


def test_white_preset_replaces_pending_color_without_sending_rgb(panel):
    state = lamp_state(); state.color_mode = 'color'
    panel.render_lamp(state, True, False, 'Confirmado', {}, True); panel.select_device('lamp')
    page = panel.lamp_page; requests = []
    page.commandRequested.connect(lambda kind, value: requests.append((kind, value)))
    page.hue.setValue(180)
    QTest.mouseClick(page.white_presets.buttons[1], Qt.MouseButton.LeftButton)
    QTest.qWait(470)
    assert requests == [('kelvin', 4000)]
    assert page.white_presets.current == -1 and state.color_mode == 'color'


@pytest.mark.parametrize('online,power,busy', [(False, True, False), (True, False, False), (True, True, True)])
def test_white_presets_cannot_actuate_when_unavailable(panel, online, power, busy):
    state = lamp_state(); state.power = power
    panel.render_lamp(state, online, busy, '', {}, True); panel.select_device('lamp')
    requests = []; page = panel.lamp_page
    page.commandRequested.connect(lambda *args: requests.append(args))
    QTest.mouseClick(page.white_presets.buttons[0], Qt.MouseButton.LeftButton)
    page.apply_white_preset('cool')
    assert requests == []
    assert not page.white_presets.buttons[0].isEnabled()


def test_white_presets_respect_capability_and_reported_kelvin_limits(panel):
    state = lamp_state(); state.maximum_kelvin = 5000
    panel.render_lamp(state, True, False, '', {}, True)
    assert not panel.lamp_page.white_presets.buttons[2].isEnabled()
    state.capabilities = frozenset({'switch', 'switchLevel'})
    panel.render_lamp(state, True, False, '', {}, True)
    requests = []; panel.lamp_page.commandRequested.connect(lambda *args: requests.append(args))
    panel.lamp_page.apply_white_preset('warm')
    assert panel.lamp_page.white_section.isHidden() and requests == []


def test_failed_white_preset_restores_confirmed_slider_and_selection(panel):
    state = lamp_state(); state.kelvin = 3000; state.color_mode = 'white'
    panel.render_lamp(state, True, False, '', {}, True); panel.select_device('lamp')
    page = panel.lamp_page
    QTest.mouseClick(page.white_presets.buttons[2], Qt.MouseButton.LeftButton)
    assert page.kelvin.value() == 6500 and page.white_presets.current == 0
    panel.render_lamp(state, True, False, 'Não confirmado', {}, True, error=True)
    assert page.kelvin.value() == 3000 and page.white_presets.current == 0


def test_settings_update_button_requests_a_check(panel):
    requests = []
    panel.updateRequested.connect(lambda: requests.append('update'))
    panel.show_page(1)
    QTest.mouseClick(panel.update_button, Qt.MouseButton.LeftButton)
    assert requests == ['update']


def test_update_button_shows_progress_and_latest_build(panel):
    panel.set_update_state('Verificando…', False)
    assert panel.update_status.text() == 'Verificando…' and not panel.update_button.isEnabled()
    panel.set_update_state('Build 7 · o mais recente')
    assert panel.update_status.text() == 'Build 7 · o mais recente' and panel.update_button.isEnabled()

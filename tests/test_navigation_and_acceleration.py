import re
import pytest

def read_source():
    with open("f0_mtg.c", "r", encoding="utf-8") as f:
        return f.read()

# ============================================================================
# 1. C Source Code Static Analysis Tests
# ============================================================================

def test_source_model_has_last_aux_focus():
    src = read_source()
    assert "MtgFocus last_aux_focus;" in src, "MtgModel must contain last_aux_focus"

def test_source_app_alloc_initializes_last_aux_focus():
    src = read_source()
    assert "app->model->last_aux_focus = FocusPoison;" in src

def test_source_focus_wrap_around():
    src = read_source()
    cycle_fn = re.search(
        r"static void f0_mtg_cycle_focus\(MtgModel\* model, bool forward\)\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    assert cycle_fn is not None, "f0_mtg_cycle_focus function not found"
    body = cycle_fn.group(1)
    assert "model->focus >= FocusCmdr3" in body or "model->focus == FocusCmdr3" in body
    assert "model->focus = FocusLife;" in body
    assert "model->focus <= FocusLife" in body or "model->focus == FocusLife" in body
    assert "model->focus = FocusCmdr3;" in body
    assert "model->last_aux_focus = model->focus;" in body

def test_source_focus_jump():
    src = read_source()
    jump_fn = re.search(
        r"static void f0_mtg_focus_jump\(MtgModel\* model\)\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    assert jump_fn is not None, "f0_mtg_focus_jump function not found"
    body = jump_fn.group(1)
    assert "model->focus != FocusLife" in body
    assert "model->focus = FocusLife;" in body
    assert "model->focus = model->last_aux_focus;" in body

def test_source_value_clamping():
    src = read_source()
    adjust_fn = re.search(
        r"static void f0_mtg_adjust_focused_counter\(MtgModel\* model, int16_t delta, uint32_t now_tick\)\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    assert adjust_fn is not None, "f0_mtg_adjust_focused_counter function not found"
    body = adjust_fn.group(1)
    # Life clamping (-99 to 999)
    assert "999" in body
    assert "-99" in body
    # Aux clamping (0 to 99)
    assert "99" in body
    assert "0" in body
    # Delta and touch tick on life only
    assert "model->life_delta += actual_delta;" in body or "model->life_delta +=" in body
    assert "model->last_life_touch_tick = now_tick;" in body

def test_source_acceleration_engine_timing():
    src = read_source()
    # 400ms stage 1 threshold and 1400ms stage 2 threshold
    assert "400" in src
    assert "1400" in src
    # Throttle intervals 100ms and 150ms
    assert "100" in src
    assert "150" in src
    # Shift to +/-5 in stage 2
    assert "dir * 5" in src or "* 5" in src

def test_source_modal_long_press_threshold():
    src = read_source()
    assert "1200" in src, "Modal open long press threshold must be 1200ms"

def test_source_delta_inactivity_timeout():
    src = read_source()
    assert "3000" in src, "3-second delta inactivity timeout must be present"
    assert "app->model->life_delta = 0;" in src

def test_source_thread_safety_mutex_and_viewport_updates():
    src = read_source()
    app_fn = re.search(
        r"int32_t f0_mtg_app\(void\* p\)\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    assert app_fn is not None, "f0_mtg_app not found"
    body = app_fn.group(1)
    # Check mutex locking is pervasive
    assert body.count("furi_mutex_acquire") >= 5
    assert body.count("furi_mutex_release") >= 5
    assert body.count("view_port_update") >= 5

def test_source_reset_match_and_toggle_format():
    src = read_source()
    reset_fn = re.search(
        r"static void f0_mtg_reset_match\(MtgModel\* model\)\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    assert reset_fn is not None
    body = reset_fn.group(1)
    assert "20" in body
    assert "40" in body
    assert "model->save_data.poison = 0;" in body
    assert "model->life_delta = 0;" in body
    assert "model->focus = FocusLife;" in body
    assert "model->last_aux_focus = FocusPoison;" in body
    assert "model->modal_open = false;" in body


# ============================================================================
# 2. Complete State Machine & Input Simulation
# ============================================================================

class MtgFocus:
    FocusLife = 0
    FocusPoison = 1
    FocusCmdr1 = 2
    FocusCmdr2 = 3
    FocusCmdr3 = 4

class MtgFormat:
    FormatEDH = 0
    FormatStandard = 1

class DialogSelection:
    DialogSelectReset = 0
    DialogSelectFormat = 1

class InputType:
    InputTypePress = 0
    InputTypeRelease = 1
    InputTypeShort = 2
    InputTypeLong = 3
    InputTypeRepeat = 4

class InputKey:
    InputKeyUp = 0
    InputKeyDown = 1
    InputKeyRight = 2
    InputKeyLeft = 3
    InputKeyOk = 4
    InputKeyBack = 5

class MtgStateMachine:
    """Exact simulation of f0_mtg.c model and event processing loop."""
    def __init__(self, format=MtgFormat.FormatEDH):
        self.format = format
        self.life = 40 if format == MtgFormat.FormatEDH else 20
        self.poison = 0
        self.cmdr_dmg = [0, 0, 0]
        self.life_delta = 0
        self.last_life_touch_tick = 0
        self.focus = MtgFocus.FocusLife
        self.last_aux_focus = MtgFocus.FocusPoison
        self.edit_mode = False
        self.modal_open = False
        self.modal_selection = DialogSelection.DialogSelectReset
        self.running = True
        self.viewport_updates = 0

        # Input tracking state
        self.ok_press_tick = 0
        self.ok_held = False
        self.ok_modal_opened = False
        self.ok_short_handled = False

        self.repeat_active = False
        self.repeat_key = None
        self.repeat_press_start_tick = 0
        self.repeat_last_tick = 0

        self.modal_toggle_pressed = False
        self.lr_pressed = False
        self.updown_pressed = False
        self.back_pressed = False

        self.modal_dismiss_key = None

    def check_delta_timeout(self, now):
        if self.life_delta != 0 and (now - self.last_life_touch_tick >= 3000):
            self.life_delta = 0
            self.viewport_updates += 1

        if self.ok_held and not self.ok_modal_opened and (now - self.ok_press_tick >= 1200):
            self.modal_open = True
            self.modal_selection = DialogSelection.DialogSelectReset
            self.ok_modal_opened = True
            self.viewport_updates += 1

    def adjust_focused_counter(self, delta, now):
        if self.focus == MtgFocus.FocusLife:
            new_life = self.life + delta
            if new_life > 999:
                new_life = 999
            elif new_life < -99:
                new_life = -99
            actual_delta = new_life - self.life
            self.life = new_life
            self.life_delta += actual_delta
            self.last_life_touch_tick = now
        else:
            if self.focus == MtgFocus.FocusPoison:
                new_val = self.poison + delta
                self.poison = max(0, min(99, new_val))
            elif self.focus == MtgFocus.FocusCmdr1:
                new_val = self.cmdr_dmg[0] + delta
                self.cmdr_dmg[0] = max(0, min(99, new_val))
            elif self.focus == MtgFocus.FocusCmdr2:
                new_val = self.cmdr_dmg[1] + delta
                self.cmdr_dmg[1] = max(0, min(99, new_val))
            elif self.focus == MtgFocus.FocusCmdr3:
                new_val = self.cmdr_dmg[2] + delta
                self.cmdr_dmg[2] = max(0, min(99, new_val))

    def reset_match(self):
        self.life = 20 if self.format == MtgFormat.FormatStandard else 40
        self.poison = 0
        self.cmdr_dmg = [0, 0, 0]
        self.life_delta = 0
        self.focus = MtgFocus.FocusLife
        self.last_aux_focus = MtgFocus.FocusPoison
        self.modal_open = False

    def toggle_format(self):
        self.format = MtgFormat.FormatStandard if self.format == MtgFormat.FormatEDH else MtgFormat.FormatEDH
        self.reset_match()

    def cycle_focus(self, forward):
        if forward:
            if self.focus >= MtgFocus.FocusCmdr3:
                self.focus = MtgFocus.FocusLife
            else:
                self.focus += 1
        else:
            if self.focus <= MtgFocus.FocusLife:
                self.focus = MtgFocus.FocusCmdr3
            else:
                self.focus -= 1

        if self.focus != MtgFocus.FocusLife:
            self.last_aux_focus = self.focus

    def focus_jump(self):
        if self.focus != MtgFocus.FocusLife:
            self.focus = MtgFocus.FocusLife
        else:
            if self.last_aux_focus < MtgFocus.FocusPoison or self.last_aux_focus > MtgFocus.FocusCmdr3:
                self.last_aux_focus = MtgFocus.FocusPoison
            self.focus = self.last_aux_focus

    def handle_input(self, event_type, key, now):
        self.check_delta_timeout(now)

        if self.modal_open:
            if key in (InputKey.InputKeyUp, InputKey.InputKeyDown):
                if event_type == InputType.InputTypePress:
                    self.modal_toggle_pressed = True
                    self.modal_selection = (
                        DialogSelection.DialogSelectFormat
                        if self.modal_selection == DialogSelection.DialogSelectReset
                        else DialogSelection.DialogSelectReset
                    )
                    self.viewport_updates += 1
                elif event_type == InputType.InputTypeShort:
                    if not self.modal_toggle_pressed:
                        self.modal_selection = (
                            DialogSelection.DialogSelectFormat
                            if self.modal_selection == DialogSelection.DialogSelectReset
                            else DialogSelection.DialogSelectReset
                        )
                        self.viewport_updates += 1
                    self.modal_toggle_pressed = False
                elif event_type == InputType.InputTypeRelease:
                    self.modal_toggle_pressed = False
            elif key == InputKey.InputKeyOk:
                if event_type in (InputType.InputTypeRelease, InputType.InputTypeShort):
                    if self.ok_modal_opened:
                        self.ok_modal_opened = False
                        self.ok_held = False
                        return
                if event_type == InputType.InputTypePress:
                    self.modal_dismiss_key = InputKey.InputKeyOk
                    if self.modal_selection == DialogSelection.DialogSelectFormat:
                        self.toggle_format()
                    else:
                        self.reset_match()
                    self.viewport_updates += 1
                elif event_type == InputType.InputTypeShort:
                    if self.modal_dismiss_key != InputKey.InputKeyOk:
                        self.modal_dismiss_key = InputKey.InputKeyOk
                        if self.modal_selection == DialogSelection.DialogSelectFormat:
                            self.toggle_format()
                        else:
                            self.reset_match()
                        self.viewport_updates += 1
            elif key == InputKey.InputKeyBack:
                if event_type == InputType.InputTypePress:
                    self.modal_dismiss_key = InputKey.InputKeyBack
                    self.modal_open = False
                    self.viewport_updates += 1
                elif event_type == InputType.InputTypeShort:
                    if self.modal_dismiss_key != InputKey.InputKeyBack:
                        self.modal_dismiss_key = InputKey.InputKeyBack
                        self.modal_open = False
                        self.viewport_updates += 1
        else:
            if self.modal_dismiss_key is not None:
                if key == self.modal_dismiss_key:
                    if event_type == InputType.InputTypeRelease:
                        return
                    if event_type == InputType.InputTypeShort:
                        self.modal_dismiss_key = None
                        return
                self.modal_dismiss_key = None

            if key == InputKey.InputKeyBack:
                if event_type == InputType.InputTypePress:
                    self.back_pressed = True
                    self.running = False
                elif event_type == InputType.InputTypeShort:
                    if not self.back_pressed:
                        self.running = False
                    self.back_pressed = False
                elif event_type == InputType.InputTypeRelease:
                    self.back_pressed = False
            elif key in (InputKey.InputKeyLeft, InputKey.InputKeyRight):
                forward = (key == InputKey.InputKeyRight)
                if event_type == InputType.InputTypePress:
                    self.lr_pressed = True
                    self.cycle_focus(forward)
                    self.viewport_updates += 1
                elif event_type == InputType.InputTypeShort:
                    if not self.lr_pressed:
                        self.cycle_focus(forward)
                        self.viewport_updates += 1
                    self.lr_pressed = False
                elif event_type == InputType.InputTypeRelease:
                    self.lr_pressed = False
            elif key == InputKey.InputKeyOk:
                if event_type == InputType.InputTypePress:
                    self.ok_press_tick = now
                    self.ok_held = True
                    self.ok_modal_opened = False
                    self.ok_short_handled = False
                elif event_type == InputType.InputTypeRepeat:
                    if not self.ok_modal_opened and (now - self.ok_press_tick >= 1200):
                        self.modal_open = True
                        self.modal_selection = DialogSelection.DialogSelectReset
                        self.ok_modal_opened = True
                        self.viewport_updates += 1
                elif event_type == InputType.InputTypeRelease:
                    self.ok_held = False
                    if not self.ok_modal_opened and (now - self.ok_press_tick < 1200):
                        self.focus_jump()
                        self.ok_short_handled = True
                        self.viewport_updates += 1
                    self.ok_modal_opened = False
                elif event_type == InputType.InputTypeShort:
                    if not self.ok_modal_opened and not self.ok_short_handled:
                        self.focus_jump()
                        self.ok_short_handled = True
                        self.viewport_updates += 1
            elif key in (InputKey.InputKeyUp, InputKey.InputKeyDown):
                dir = 1 if key == InputKey.InputKeyUp else -1
                if event_type == InputType.InputTypePress:
                    self.repeat_active = True
                    self.repeat_key = key
                    self.repeat_press_start_tick = now
                    self.repeat_last_tick = now
                    self.updown_pressed = True
                    self.adjust_focused_counter(dir, now)
                    self.viewport_updates += 1
                elif event_type == InputType.InputTypeRepeat:
                    if self.repeat_active and self.repeat_key == key:
                        hold_duration = now - self.repeat_press_start_tick
                        if 400 <= hold_duration <= 1400:
                            if now - self.repeat_last_tick >= 100:
                                self.adjust_focused_counter(dir, now)
                                self.repeat_last_tick = now
                                self.viewport_updates += 1
                        elif hold_duration > 1400:
                            if now - self.repeat_last_tick >= 150:
                                self.adjust_focused_counter(dir * 5, now)
                                self.repeat_last_tick = now
                                self.viewport_updates += 1
                elif event_type == InputType.InputTypeRelease:
                    if self.repeat_active and self.repeat_key == key:
                        self.repeat_active = False
                    self.updown_pressed = False
                elif event_type == InputType.InputTypeShort:
                    if not self.updown_pressed:
                        self.adjust_focused_counter(dir, now)
                        self.viewport_updates += 1
                    self.updown_pressed = False


# ============================================================================
# 3. Focus Navigation Unit Tests
# ============================================================================

def test_focus_cycling_right_wrap_around():
    app = MtgStateMachine()
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusPoison

    expected_sequence = [
        (MtgFocus.FocusPoison, MtgFocus.FocusPoison),
        (MtgFocus.FocusCmdr1, MtgFocus.FocusCmdr1),
        (MtgFocus.FocusCmdr2, MtgFocus.FocusCmdr2),
        (MtgFocus.FocusCmdr3, MtgFocus.FocusCmdr3),
        (MtgFocus.FocusLife, MtgFocus.FocusCmdr3),  # wrap to Life, last_aux retained
        (MtgFocus.FocusPoison, MtgFocus.FocusPoison),
    ]
    now = 1000
    for exp_focus, exp_aux in expected_sequence:
        app.handle_input(InputType.InputTypePress, InputKey.InputKeyRight, now)
        app.handle_input(InputType.InputTypeShort, InputKey.InputKeyRight, now)
        assert app.focus == exp_focus
        assert app.last_aux_focus == exp_aux
        now += 100

def test_focus_cycling_left_wrap_around():
    app = MtgStateMachine()
    assert app.focus == MtgFocus.FocusLife

    expected_sequence = [
        (MtgFocus.FocusCmdr3, MtgFocus.FocusCmdr3),  # wrap from Life to Cmdr3
        (MtgFocus.FocusCmdr2, MtgFocus.FocusCmdr2),
        (MtgFocus.FocusCmdr1, MtgFocus.FocusCmdr1),
        (MtgFocus.FocusPoison, MtgFocus.FocusPoison),
        (MtgFocus.FocusLife, MtgFocus.FocusPoison),   # wrap to Life, last_aux retained
        (MtgFocus.FocusCmdr3, MtgFocus.FocusCmdr3),
    ]
    now = 1000
    for exp_focus, exp_aux in expected_sequence:
        app.handle_input(InputType.InputTypePress, InputKey.InputKeyLeft, now)
        app.handle_input(InputType.InputTypeShort, InputKey.InputKeyLeft, now)
        assert app.focus == exp_focus
        assert app.last_aux_focus == exp_aux
        now += 100

def test_focus_jump_default():
    app = MtgStateMachine()
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusPoison

    # Short press OK on Life -> jumps to last_aux_focus (FocusPoison)
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 1100)
    assert app.focus == MtgFocus.FocusPoison

    # Short press OK on Poison -> jumps back to FocusLife
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1200)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 1300)
    assert app.focus == MtgFocus.FocusLife

def test_focus_jump_to_last_selected_aux():
    app = MtgStateMachine()
    # Cycle right to Cmdr2
    app.cycle_focus(forward=True)  # Poison
    app.cycle_focus(forward=True)  # Cmdr1
    app.cycle_focus(forward=True)  # Cmdr2
    assert app.focus == MtgFocus.FocusCmdr2
    assert app.last_aux_focus == MtgFocus.FocusCmdr2

    # Jump to Life
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 1050)
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusCmdr2

    # Jump back to Cmdr2
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1200)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 1250)
    assert app.focus == MtgFocus.FocusCmdr2


# ============================================================================
# 4. Long Press & Modal Dialog Tests
# ============================================================================

def test_ok_long_press_opens_modal():
    app = MtgStateMachine()
    assert not app.modal_open

    # Press down at t=1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    assert not app.modal_open

    # Repeat at t=1500 (500ms hold) -> not yet 1200ms
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 1500)
    assert not app.modal_open

    # Repeat at t=2199 (1199ms hold) -> still not opened
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2199)
    assert not app.modal_open

    # Repeat at t=2200 (1200ms hold) -> modal opens immediately
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2200)
    assert app.modal_open
    assert app.modal_selection == DialogSelection.DialogSelectReset

    # Release at t=2300 should NOT trigger focus jump
    orig_focus = app.focus
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2300)
    assert app.focus == orig_focus
    assert app.modal_open

def test_ok_release_before_1200ms_does_not_open_modal():
    app = MtgStateMachine()
    # Press at 1000, release at 2199 (< 1200ms)
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 1500)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2199)
    assert not app.modal_open
    # Should have performed focus jump instead
    assert app.focus == MtgFocus.FocusPoison

def test_modal_toggle_selection_up_down():
    app = MtgStateMachine()
    app.modal_open = True
    app.modal_selection = DialogSelection.DialogSelectReset

    # KeyDown toggles to Format
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1000)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyDown, 1000)
    assert app.modal_selection == DialogSelection.DialogSelectFormat

    # KeyDown toggles back to Reset
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1100)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyDown, 1100)
    assert app.modal_selection == DialogSelection.DialogSelectReset

    # KeyUp toggles to Format
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1200)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyUp, 1200)
    assert app.modal_selection == DialogSelection.DialogSelectFormat

def test_modal_keyback_dismisses_without_changes():
    app = MtgStateMachine()
    app.life = 25
    app.poison = 4
    app.cmdr_dmg = [10, 5, 0]
    app.life_delta = -15
    app.modal_open = True

    # Press Back inside modal
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyBack, 1000)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyBack, 1000)
    assert not app.modal_open
    assert app.running is True
    # All game state retained
    assert app.life == 25
    assert app.poison == 4
    assert app.cmdr_dmg == [10, 5, 0]
    assert app.life_delta == -15

def test_modal_reset_match_action():
    app = MtgStateMachine(format=MtgFormat.FormatEDH)
    app.life = 12
    app.poison = 7
    app.cmdr_dmg = [15, 8, 2]
    app.life_delta = -28
    app.focus = MtgFocus.FocusCmdr2
    app.last_aux_focus = MtgFocus.FocusCmdr2
    app.modal_open = True
    app.modal_selection = DialogSelection.DialogSelectReset

    # Press OK
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    assert not app.modal_open
    assert app.format == MtgFormat.FormatEDH
    assert app.life == 40
    assert app.poison == 0
    assert app.cmdr_dmg == [0, 0, 0]
    assert app.life_delta == 0
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusPoison

def test_modal_reset_match_standard_format():
    app = MtgStateMachine(format=MtgFormat.FormatStandard)
    app.life = 5
    app.modal_open = True
    app.modal_selection = DialogSelection.DialogSelectReset

    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    assert not app.modal_open
    assert app.format == MtgFormat.FormatStandard
    assert app.life == 20

def test_modal_toggle_format_action():
    app = MtgStateMachine(format=MtgFormat.FormatEDH)
    app.life = 35
    app.poison = 3
    app.modal_open = True
    app.modal_selection = DialogSelection.DialogSelectFormat

    # Execute toggle format
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    assert not app.modal_open
    assert app.format == MtgFormat.FormatStandard
    assert app.life == 20
    assert app.poison == 0
    assert app.cmdr_dmg == [0, 0, 0]
    assert app.life_delta == 0
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusPoison

    # Toggle back to EDH
    app.modal_open = True
    app.modal_selection = DialogSelection.DialogSelectFormat
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 2000)
    assert app.format == MtgFormat.FormatEDH
    assert app.life == 40


# ============================================================================
# 5. Input Acceleration Engine (Outside Modal)
# ============================================================================

def test_acceleration_stage1_and_stage2_timing():
    app = MtgStateMachine()
    assert app.life == 40
    assert app.focus == MtgFocus.FocusLife

    now = 1000
    # Press at t=1000 -> initial single increment (+1)
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, now)
    assert app.life == 41

    # Repeat before 400ms -> no change
    for offset in [100, 200, 300, 399]:
        app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + offset)
        assert app.life == 41

    # Stage 1 begins at hold_duration == 400ms (t=1400)
    # since now - repeat_last_tick = 400 >= 100 -> fires (+1)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 400)
    assert app.life == 42

    # Throttled to every 100ms
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 450)
    assert app.life == 42  # only 50ms elapsed, no fire

    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 500)
    assert app.life == 43  # 100ms elapsed, fires (+1)

    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 600)
    assert app.life == 44

    # Fast forward to end of Stage 1 (1400ms hold, t=2400)
    # Fire at 1400ms:
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 1400)
    life_at_end_of_stage1 = app.life

    # Stage 2 (> 1400ms hold): shifts to +/-5 throttled to every 150ms
    # At t = 2450 (1450ms hold, 50ms since last repeat): interval 150 not met
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 1450)
    assert app.life == life_at_end_of_stage1

    # At t = 2550 (1550ms hold, 150ms since last repeat): fires (+5)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 1550)
    assert app.life == life_at_end_of_stage1 + 5

    # At t = 2650 (now + 1650, 100ms since last): interval 150 not met
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 1650)
    assert app.life == life_at_end_of_stage1 + 5

    # At t = 2700 (now + 1700, 150ms since last): fires (+5)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now + 1700)
    assert app.life == life_at_end_of_stage1 + 10

    # Release ends repeat
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyUp, now + 1750)
    assert not app.repeat_active

def test_acceleration_decrement_down():
    app = MtgStateMachine()
    now = 1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, now)
    assert app.life == 39
    assert app.life_delta == -1

    # Stage 1 repeat at 400ms
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyDown, now + 400)
    assert app.life == 38
    assert app.life_delta == -2

    # Stage 2 repeat after 1400ms
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyDown, now + 1550)
    assert app.life == 33
    assert app.life_delta == -7


# ============================================================================
# 6. Value Clamping & Delta Tracking Tests
# ============================================================================

def test_life_clamping_upper():
    app = MtgStateMachine()
    app.life = 998
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.life == 999
    assert app.life_delta == 1

    # Further increment clamps at 999
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1100)
    assert app.life == 999
    assert app.life_delta == 1  # delta does not grow past 999

def test_life_clamping_lower():
    app = MtgStateMachine()
    app.life = -98
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1000)
    assert app.life == -99
    assert app.life_delta == -1

    # Further decrement clamps at -99
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1100)
    assert app.life == -99
    assert app.life_delta == -1

def test_poison_clamping_and_no_delta():
    app = MtgStateMachine()
    app.focus = MtgFocus.FocusPoison

    # Increment poison
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.poison == 1
    assert app.life_delta == 0  # aux changes must NOT alter life_delta

    # Decrement past 0 clamps to 0
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1100)
    assert app.poison == 0
    assert app.life_delta == 0
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1200)
    assert app.poison == 0

    # Upper clamp to 99
    app.poison = 98
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1300)
    assert app.poison == 99
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1400)
    assert app.poison == 99
    assert app.life_delta == 0

@pytest.mark.parametrize("cmdr_idx, focus_val", [
    (0, MtgFocus.FocusCmdr1),
    (1, MtgFocus.FocusCmdr2),
    (2, MtgFocus.FocusCmdr3),
])
def test_cmdr_dmg_clamping_and_no_delta(cmdr_idx, focus_val):
    app = MtgStateMachine()
    app.focus = focus_val

    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.cmdr_dmg[cmdr_idx] == 1
    assert app.life_delta == 0

    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1100)
    assert app.cmdr_dmg[cmdr_idx] == 0
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 1200)
    assert app.cmdr_dmg[cmdr_idx] == 0

    app.cmdr_dmg[cmdr_idx] = 98
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1300)
    assert app.cmdr_dmg[cmdr_idx] == 99
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1400)
    assert app.cmdr_dmg[cmdr_idx] == 99
    assert app.life_delta == 0

def test_life_delta_timeout_clearing():
    app = MtgStateMachine()
    # Change life at t=1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.life == 41
    assert app.life_delta == 1
    assert app.last_life_touch_tick == 1000

    # Periodic check at t=2000 (1000ms elapsed) -> delta remains
    app.check_delta_timeout(2000)
    assert app.life_delta == 1

    # Periodic check at t=3999 (2999ms elapsed) -> delta remains
    app.check_delta_timeout(3999)
    assert app.life_delta == 1

    # Periodic check at t=4000 (3000ms elapsed) -> delta cleared to 0
    app.check_delta_timeout(4000)
    assert app.life_delta == 0

def test_aux_changes_do_not_refresh_life_delta_timeout():
    app = MtgStateMachine()
    # Modify life at t=1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.life_delta == 1

    # Switch focus to Poison and change poison at t=2500
    app.focus = MtgFocus.FocusPoison
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 2500)
    assert app.poison == 1
    assert app.life_delta == 1

    # At t=4000 (3000ms after life modification at 1000) -> delta must clear despite poison change
    app.check_delta_timeout(4000)
    assert app.life_delta == 0

def test_back_button_exits_app_when_modal_closed():
    app = MtgStateMachine()
    assert app.running is True
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyBack, 1000)
    assert app.running is False

def test_save_data_struct_layout_and_size():
    import struct
    # Layout: uint32 magic, uint8 version, uint8 format, int16 life, uint8 poison, uint8 cmdr[3], uint8 reserved[20]
    # Packed format: '< I B B h B 3B 20s'
    fmt = '<IBBhB3B20s'
    size = struct.calcsize(fmt)
    assert size == 32, f"MtgSaveData packed size must be exactly 32 bytes, got {size}"

def test_delta_timeout_reset_on_consecutive_life_changes():
    app = MtgStateMachine()
    # Life touched at t=1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    assert app.life_delta == 1

    # Life touched again at t=3500 (2500ms later)
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 3500)
    assert app.life_delta == 2

    # At t=4500 (1000ms after second touch, but 3500ms after first): delta must NOT clear
    app.check_delta_timeout(4500)
    assert app.life_delta == 2

    # At t=6500 (3000ms after second touch): delta clears
    app.check_delta_timeout(6500)
    assert app.life_delta == 0

def test_ok_hold_boundary_1199_vs_1200():
    # Exactly 1199ms: releases without opening modal, performs focus jump
    app1 = MtgStateMachine()
    app1.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app1.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2199)
    assert not app1.modal_open
    app1.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2199)
    assert not app1.modal_open
    assert app1.focus == MtgFocus.FocusPoison

    # Exactly 1200ms: opens modal immediately on repeat
    app2 = MtgStateMachine()
    app2.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app2.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2200)
    assert app2.modal_open
    # Subsequent release does NOT jump
    app2.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2300)
    assert app2.focus == MtgFocus.FocusLife
    assert app2.modal_open

def test_life_extreme_clamping_acceleration():
    app = MtgStateMachine()
    app.life = 990
    now = 1000
    # Initial press: 991
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, now)
    assert app.life == 991
    # Repeat stage 2 (> 1400ms hold, +5 per step)
    now += 1550
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now)
    assert app.life == 996
    now += 150
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now)
    assert app.life == 999
    # Further stage 2 repeat attempts to add +5 -> clamped at 999
    now += 150
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now)
    assert app.life == 999
    assert app.life_delta == 9  # net change 999 - 990 = 9

def test_aux_extreme_clamping_acceleration():
    app = MtgStateMachine()
    app.focus = MtgFocus.FocusPoison
    app.poison = 95
    now = 1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, now)
    assert app.poison == 96
    now += 1550  # stage 2 (+5)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now)
    # 96 + 5 = 101 -> clamped to 99
    assert app.poison == 99
    now += 150
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, now)
    assert app.poison == 99
    assert app.life_delta == 0

def test_modal_reset_match_no_focus_leak_on_trailing_release_or_short():
    app = MtgStateMachine()
    # Hold OK to open modal
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2200)
    assert app.modal_open
    # Release opening hold
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2250)
    assert app.modal_open

    # In modal, press OK to Reset Match
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 3000)
    assert not app.modal_open
    assert app.focus == MtgFocus.FocusLife

    # Release and Short delivered by OS for the OK click
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 3050)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyOk, 3050)

    # Focus must remain FocusLife (0), NOT leak into FocusPoison (1)
    assert app.focus == MtgFocus.FocusLife
    assert app.last_aux_focus == MtgFocus.FocusPoison

def test_modal_toggle_format_no_focus_leak_on_trailing_release_or_short():
    app = MtgStateMachine(format=MtgFormat.FormatEDH)
    # Hold OK to open modal
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyOk, 2200)
    assert app.modal_open
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 2250)

    # In modal, toggle selection to Format
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyDown, 2500)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyDown, 2500)
    assert app.modal_selection == DialogSelection.DialogSelectFormat

    # Press OK to Toggle Format
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 3000)
    assert not app.modal_open
    assert app.format == MtgFormat.FormatStandard
    assert app.life == 20
    assert app.focus == MtgFocus.FocusLife

    # Trailing Release and Short from OK click must NOT leak into main screen jump
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyOk, 3050)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyOk, 3050)
    assert app.focus == MtgFocus.FocusLife

def test_modal_dismiss_back_no_app_exit_leak():
    app = MtgStateMachine()
    app.modal_open = True
    # Press Back in modal to dismiss
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyBack, 1000)
    assert not app.modal_open
    assert app.running is True

    # Trailing Release and Short from Back click must NOT exit app
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyBack, 1050)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyBack, 1050)
    assert app.running is True

    # Subsequent Back press on main screen exits app
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyBack, 2000)
    assert app.running is False

def test_long_hold_up_release_does_not_block_subsequent_short_press():
    app = MtgStateMachine()
    # Long hold Up to adjust life
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyUp, 1000)
    app.handle_input(InputType.InputTypeRepeat, InputKey.InputKeyUp, 1500)
    app.handle_input(InputType.InputTypeRelease, InputKey.InputKeyUp, 2000)
    assert app.life > 40

    # User taps Right to cycle focus (press + short)
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyRight, 2500)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyRight, 2500)
    assert app.focus == MtgFocus.FocusPoison

    # User taps Right using only Short (simulating single event injection)
    app.handle_input(InputType.InputTypeShort, InputKey.InputKeyRight, 2600)
    assert app.focus == MtgFocus.FocusCmdr1

def test_ok_long_press_detection_via_tick_timeout_without_repeat():
    app = MtgStateMachine()
    # Press OK at t=1000
    app.handle_input(InputType.InputTypePress, InputKey.InputKeyOk, 1000)
    assert not app.modal_open

    # Simulate periodic queue wait timeout checking delta and ticks at t=2100 (1100ms: not yet)
    app.check_delta_timeout(2100)
    assert not app.modal_open

    # Tick at t=2200 (1200ms elapsed): opens modal directly on tick check!
    app.check_delta_timeout(2200)
    assert app.modal_open
    assert app.modal_selection == DialogSelection.DialogSelectReset

def test_source_guards_and_mutex_discipline():
    src = read_source()
    assert "modal_dismiss_key" in src, "f0_mtg.c must track modal_dismiss_key to prevent event leakage"
    assert "ok_held" in src, "f0_mtg.c must track ok_held for tick-based modal detection"



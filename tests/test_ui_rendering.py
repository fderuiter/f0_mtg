import re
import pytest

def read_source():
    with open("f0_mtg.c", "r", encoding="utf-8") as f:
        return f.read()

def test_includes_and_definitions():
    src = read_source()
    assert "#include <furi_hal_power.h>" in src
    assert "DialogSelectReset = 0" in src
    assert "DialogSelectFormat = 1" in src
    assert "MtgModel" in src
    assert "dialog_selection" in src
    assert "modal_selection" in src
    assert "dialog_open" in src
    assert "modal_open" in src

def test_thread_safety_mutex():
    src = read_source()
    render_cb_match = re.search(r"static void f0_mtg_render_callback\(Canvas\* canvas, void\* context\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert render_cb_match is not None, "f0_mtg_render_callback not found"
    body = render_cb_match.group(1)
    
    # Check mutex acquire at start
    assert "furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);" in body
    # Check mutex release at end
    assert "furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);" in body
    # Acquire must precede release
    acquire_pos = body.find("furi_mutex_acquire")
    release_pos = body.find("furi_mutex_release")
    assert acquire_pos < release_pos

def test_row0_header():
    src = read_source()
    # Format strings
    assert '"EDH [40]"' in src
    assert '"STD [20]"' in src
    assert "FormatStandard" in src
    # Battery readout & glyph
    assert "furi_hal_power_get_pct()" in src
    assert "canvas_draw_frame(canvas, 117, 2, 9, 6);" in src
    assert "canvas_draw_line(canvas, 0, 10, 127, 10);" in src

def test_row1_transient_delta():
    src = read_source()
    assert "app->model->life_delta != 0" in src
    assert '"%+d"' in src
    assert "canvas_draw_str_aligned(canvas, 64, 15, AlignCenter, AlignCenter, delta_str);" in src

def test_row2_primary_life():
    src = read_source()
    assert "canvas_draw_box(canvas, 28, 20, 72, 24);" in src
    assert "canvas_draw_frame(canvas, 24, 19, 80, 26);" in src
    assert "FontBigNumbers" in src
    assert "canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, life_str);" in src

def test_row3_aux_matrix():
    src = read_source()
    assert '"P:%u"' in src
    assert '"C1:%u"' in src
    assert '"C2:%u"' in src
    assert '"C3:%u"' in src
    # Poison lethal threshold
    assert "poison >= 10" in src
    # Cmdr lethal threshold
    assert "cmdr_dmg[0] >= 21" in src
    assert "cmdr_dmg[1] >= 21" in src
    assert "cmdr_dmg[2] >= 21" in src
    # Inset frame
    assert "canvas_draw_frame(canvas, cell_x + 1, 46, 30, 8);" in src
    # Invert cell box
    assert "canvas_draw_box(canvas, cell_x, 45, 32, 10);" in src
    # Vertical divider lines
    assert "canvas_draw_line(canvas, 32, 45, 32, 54);" in src
    assert "canvas_draw_line(canvas, 64, 45, 64, 54);" in src
    assert "canvas_draw_line(canvas, 96, 45, 96, 54);" in src

def test_row4_nav_bar():
    src = read_source()
    assert "canvas_draw_box(canvas, 0, 55, 128, 9);" in src
    assert '"[UP/DN] +/-1  [OK] Done"' in src
    assert '"[< >] Select  [OK] Edit"' in src
    assert "canvas_draw_str_aligned(canvas, 64, 59, AlignCenter, AlignCenter, nav_text);" in src

def test_modal_dialog():
    src = read_source()
    assert "canvas_draw_rbox(canvas, 14, 14, 100, 36, 3);" in src
    assert "canvas_draw_rframe(canvas, 14, 14, 100, 36, 3);" in src
    assert '"> Reset Match <"' in src
    assert '"Reset Match"' in src
    assert '"> Toggle Format <"' in src
    assert '"Toggle Format"' in src
    assert "canvas_draw_str_aligned(canvas, 64, 26, AlignCenter, AlignCenter, reset_str);" in src
    assert "canvas_draw_str_aligned(canvas, 64, 38, AlignCenter, AlignCenter, toggle_format_str);" in src

# Simulation test for rendering logic behavior across states
class MockCanvas:
    def __init__(self):
        self.operations = []
        self.color = "ColorBlack"
        self.font = "FontSecondary"

    def set_color(self, color):
        self.color = color
        self.operations.append(("set_color", color))

    def set_font(self, font):
        self.font = font
        self.operations.append(("set_font", font))

    def clear(self):
        self.operations.append(("clear",))

    def draw_str_aligned(self, x, y, align_x, align_y, text):
        self.operations.append(("draw_str_aligned", x, y, align_x, align_y, text, self.color, self.font))

    def draw_line(self, x1, y1, x2, y2):
        self.operations.append(("draw_line", x1, y1, x2, y2, self.color))

    def draw_box(self, x, y, w, h):
        self.operations.append(("draw_box", x, y, w, h, self.color))

    def draw_frame(self, x, y, w, h):
        self.operations.append(("draw_frame", x, y, w, h, self.color))

    def draw_rbox(self, x, y, w, h, r):
        self.operations.append(("draw_rbox", x, y, w, h, r, self.color))

    def draw_rframe(self, x, y, w, h, r):
        self.operations.append(("draw_rframe", x, y, w, h, r, self.color))

def simulate_render(model, battery_pct=85):
    c = MockCanvas()
    c.clear()

    # Row 0
    c.set_color("ColorBlack")
    c.set_font("FontSecondary")
    format_str = "STD [20]" if model["format"] == 1 else "EDH [40]"
    c.draw_str_aligned(2, 5, "AlignLeft", "AlignCenter", format_str)

    bat = min(battery_pct, 100)
    c.draw_str_aligned(114, 5, "AlignRight", "AlignCenter", f"{bat}%")
    c.draw_frame(117, 2, 9, 6)
    fill_w = (bat * 7 + 50) // 100
    if bat > 0 and fill_w == 0:
        fill_w = 1
    if fill_w > 7:
        fill_w = 7
    if fill_w > 0:
        c.draw_box(118, 3, fill_w, 4)
    c.draw_line(0, 10, 127, 10)

    # Row 1
    if model["life_delta"] != 0:
        c.set_font("FontSecondary")
        sign = "+" if model["life_delta"] > 0 else ""
        c.draw_str_aligned(64, 15, "AlignCenter", "AlignCenter", f"{sign}{model['life_delta']}")

    # Row 2
    life_str = str(model["life"])
    if model["life"] <= 0:
        c.set_color("ColorBlack")
        c.draw_box(28, 20, 72, 24)
        c.set_color("ColorWhite")
        c.set_font("FontBigNumbers")
        c.draw_str_aligned(64, 32, "AlignCenter", "AlignCenter", life_str)
        c.set_color("ColorBlack")
    else:
        c.set_color("ColorBlack")
        c.set_font("FontBigNumbers")
        c.draw_str_aligned(64, 32, "AlignCenter", "AlignCenter", life_str)

    if model["focus"] == 0:  # FocusLife
        c.set_color("ColorBlack")
        c.draw_frame(24, 19, 80, 26)

    # Row 3
    aux_cells = [
        ("P:%u", model["poison"], 1, model["poison"] >= 10),
        ("C1:%u", model["cmdr_dmg"][0], 2, model["cmdr_dmg"][0] >= 21),
        ("C2:%u", model["cmdr_dmg"][1], 3, model["cmdr_dmg"][1] >= 21),
        ("C3:%u", model["cmdr_dmg"][2], 4, model["cmdr_dmg"][2] >= 21),
    ]
    c.set_font("FontSecondary")
    for i in range(4):
        cell_x = i * 32
        is_focused = (model["focus"] == aux_cells[i][2])
        is_lethal = aux_cells[i][3]
        cell_str = aux_cells[i][0].replace("%u", str(aux_cells[i][1]))

        if is_focused:
            c.set_color("ColorBlack")
            c.draw_box(cell_x, 45, 32, 10)
            if is_lethal:
                c.set_color("ColorWhite")
                c.draw_frame(cell_x + 1, 46, 30, 8)
            c.set_color("ColorWhite")
            c.draw_str_aligned(cell_x + 16, 50, "AlignCenter", "AlignCenter", cell_str)
            c.set_color("ColorBlack")
        else:
            if is_lethal:
                c.set_color("ColorBlack")
                c.draw_frame(cell_x + 1, 46, 30, 8)
            c.set_color("ColorBlack")
            c.draw_str_aligned(cell_x + 16, 50, "AlignCenter", "AlignCenter", cell_str)

    c.set_color("ColorBlack")
    c.draw_line(32, 45, 32, 54)
    c.draw_line(64, 45, 64, 54)
    c.draw_line(96, 45, 96, 54)

    # Row 4
    c.set_color("ColorBlack")
    c.draw_box(0, 55, 128, 9)
    c.set_color("ColorWhite")
    c.set_font("FontSecondary")
    nav_text = "[UP/DN] +/-1  [OK] Done" if model["edit_mode"] else "[< >] Select  [OK] Edit"
    c.draw_str_aligned(64, 59, "AlignCenter", "AlignCenter", nav_text)
    c.set_color("ColorBlack")

    # Modal
    is_modal = model.get("modal_open") or model.get("dialog_open", False)
    if is_modal:
        c.set_color("ColorWhite")
        c.draw_rbox(14, 14, 100, 36, 3)
        c.set_color("ColorBlack")
        c.draw_rframe(14, 14, 100, 36, 3)
        c.set_font("FontSecondary")
        sel = model.get("modal_selection") if "modal_selection" in model else model.get("dialog_selection", 0)
        reset_str = "> Reset Match <" if sel == 0 else "Reset Match"
        toggle_format_str = "> Toggle Format <" if sel == 1 else "Toggle Format"
        c.draw_str_aligned(64, 26, "AlignCenter", "AlignCenter", reset_str)
        c.draw_str_aligned(64, 38, "AlignCenter", "AlignCenter", toggle_format_str)

    return c

def test_simulation_default_state():
    model = {
        "format": 0,
        "life": 40,
        "poison": 0,
        "cmdr_dmg": [0, 0, 0],
        "life_delta": 0,
        "focus": 0,  # FocusLife
        "edit_mode": False,
        "dialog_open": False,
        "dialog_selection": 0,
    }
    c = simulate_render(model, battery_pct=75)
    ops = c.operations
    assert ("clear",) in ops
    # Format EDH [40]
    assert ("draw_str_aligned", 2, 5, "AlignLeft", "AlignCenter", "EDH [40]", "ColorBlack", "FontSecondary") in ops
    # Battery readout & glyph
    assert ("draw_str_aligned", 114, 5, "AlignRight", "AlignCenter", "75%", "ColorBlack", "FontSecondary") in ops
    assert ("draw_frame", 117, 2, 9, 6, "ColorBlack") in ops
    # Divider line
    assert ("draw_line", 0, 10, 127, 10, "ColorBlack") in ops
    # No delta rendered
    assert not any(op[0] == "draw_str_aligned" and op[2] == 15 for op in ops)
    # Primary life
    assert ("draw_str_aligned", 64, 32, "AlignCenter", "AlignCenter", "40", "ColorBlack", "FontBigNumbers") in ops
    assert ("draw_frame", 24, 19, 80, 26, "ColorBlack") in ops
    # Aux cells
    assert ("draw_str_aligned", 16, 50, "AlignCenter", "AlignCenter", "P:0", "ColorBlack", "FontSecondary") in ops
    assert ("draw_str_aligned", 48, 50, "AlignCenter", "AlignCenter", "C1:0", "ColorBlack", "FontSecondary") in ops
    # Dividers
    assert ("draw_line", 32, 45, 32, 54, "ColorBlack") in ops
    assert ("draw_line", 64, 45, 64, 54, "ColorBlack") in ops
    assert ("draw_line", 96, 45, 96, 54, "ColorBlack") in ops
    # Nav bar
    assert ("draw_box", 0, 55, 128, 9, "ColorBlack") in ops
    assert ("draw_str_aligned", 64, 59, "AlignCenter", "AlignCenter", "[< >] Select  [OK] Edit", "ColorWhite", "FontSecondary") in ops
    # No modal
    assert not any(op[0] == "draw_rbox" for op in ops)

def test_simulation_lethal_and_inverted():
    model = {
        "format": 1,  # STD [20]
        "life": -2,
        "poison": 10,  # Lethal and focused
        "cmdr_dmg": [21, 5, 0],  # C1 lethal but unfocused
        "life_delta": -5,
        "focus": 1,  # FocusPoison
        "edit_mode": True,
        "dialog_open": False,
        "dialog_selection": 0,
    }
    c = simulate_render(model, battery_pct=10)
    ops = c.operations
    # Format STD [20]
    assert ("draw_str_aligned", 2, 5, "AlignLeft", "AlignCenter", "STD [20]", "ColorBlack", "FontSecondary") in ops
    # Delta
    assert ("draw_str_aligned", 64, 15, "AlignCenter", "AlignCenter", "-5", "ColorBlack", "FontSecondary") in ops
    # Life <= 0 inverted box and white text
    assert ("draw_box", 28, 20, 72, 24, "ColorBlack") in ops
    assert ("draw_str_aligned", 64, 32, "AlignCenter", "AlignCenter", "-2", "ColorWhite", "FontBigNumbers") in ops
    # Focus not on life, so no life bounding frame
    assert ("draw_frame", 24, 19, 80, 26, "ColorBlack") not in ops
    # FocusPoison: inverted black box (0, 45, 32, 10), contrasting white frame (1, 46, 30, 8), white text
    assert ("draw_box", 0, 45, 32, 10, "ColorBlack") in ops
    assert ("draw_frame", 1, 46, 30, 8, "ColorWhite") in ops
    assert ("draw_str_aligned", 16, 50, "AlignCenter", "AlignCenter", "P:10", "ColorWhite", "FontSecondary") in ops
    # C1 lethal unfocused: black frame (33, 46, 30, 8), black text
    assert ("draw_frame", 33, 46, 30, 8, "ColorBlack") in ops
    assert ("draw_str_aligned", 48, 50, "AlignCenter", "AlignCenter", "C1:21", "ColorBlack", "FontSecondary") in ops
    # Nav bar in edit mode
    assert ("draw_str_aligned", 64, 59, "AlignCenter", "AlignCenter", "[UP/DN] +/-1  [OK] Done", "ColorWhite", "FontSecondary") in ops

def test_simulation_modal_dialog():
    model = {
        "format": 0,
        "life": 40,
        "poison": 0,
        "cmdr_dmg": [0, 0, 0],
        "life_delta": 0,
        "focus": 0,
        "edit_mode": False,
        "dialog_open": True,
        "dialog_selection": 1,  # Toggle Format
    }
    c = simulate_render(model, battery_pct=50)
    ops = c.operations
    assert ("draw_rbox", 14, 14, 100, 36, 3, "ColorWhite") in ops
    assert ("draw_rframe", 14, 14, 100, 36, 3, "ColorBlack") in ops
    assert ("draw_str_aligned", 64, 26, "AlignCenter", "AlignCenter", "Reset Match", "ColorBlack", "FontSecondary") in ops
    assert ("draw_str_aligned", 64, 38, "AlignCenter", "AlignCenter", "> Toggle Format <", "ColorBlack", "FontSecondary") in ops

@pytest.mark.parametrize("pct, expected_fill_w", [
    (0, 0),
    (1, 1),
    (10, 1),
    (50, 4),
    (99, 7),
    (100, 7),
    (120, 7),
])
def test_battery_fill_calculation(pct, expected_fill_w):
    model = {
        "format": 0, "life": 20, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model, battery_pct=pct)
    ops = c.operations
    if expected_fill_w == 0:
        assert not any(op[0] == "draw_box" and op[1] == 118 for op in ops)
    else:
        assert ("draw_box", 118, 3, expected_fill_w, 4, "ColorBlack") in ops

@pytest.mark.parametrize("poison, is_lethal", [
    (0, False),
    (9, False),
    (10, True),
    (11, True),
])
def test_poison_lethal_threshold(poison, is_lethal):
    model = {
        "format": 0, "life": 20, "poison": poison, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    # Unfocused cell 0 lethal border: (1, 46, 30, 8)
    has_frame = ("draw_frame", 1, 46, 30, 8, "ColorBlack") in ops
    assert has_frame == is_lethal

@pytest.mark.parametrize("cmdr, is_lethal", [
    (0, False),
    (20, False),
    (21, True),
    (22, True),
])
def test_cmdr_lethal_threshold(cmdr, is_lethal):
    model = {
        "format": 0, "life": 20, "poison": 0, "cmdr_dmg": [cmdr, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    # Unfocused cell 1 lethal border: (33, 46, 30, 8)
    has_frame = ("draw_frame", 33, 46, 30, 8, "ColorBlack") in ops
    assert has_frame == is_lethal

@pytest.mark.parametrize("life, expect_box", [
    (40, False),
    (1, False),
    (0, True),
    (-1, True),
    (-20, True),
])
def test_life_death_indicator(life, expect_box):
    model = {
        "format": 0, "life": life, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    has_black_box = ("draw_box", 28, 20, 72, 24, "ColorBlack") in ops
    assert has_black_box == expect_box

def test_simulation_dead_and_focused_life():
    model = {
        "format": 0, "life": 0, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    # Both death box AND focus bounding frame should be present
    assert ("draw_box", 28, 20, 72, 24, "ColorBlack") in ops
    assert ("draw_frame", 24, 19, 80, 26, "ColorBlack") in ops
    assert ("draw_str_aligned", 64, 32, "AlignCenter", "AlignCenter", "0", "ColorWhite", "FontBigNumbers") in ops

def test_simulation_positive_life_delta():
    model = {
        "format": 0, "life": 20, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 5, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    assert ("draw_str_aligned", 64, 15, "AlignCenter", "AlignCenter", "+5", "ColorBlack", "FontSecondary") in ops

def test_simulation_modal_selection_reset():
    model = {
        "format": 0, "life": 40, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "dialog_open": True, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    assert ("draw_str_aligned", 64, 26, "AlignCenter", "AlignCenter", "> Reset Match <", "ColorBlack", "FontSecondary") in ops
    assert ("draw_str_aligned", 64, 38, "AlignCenter", "AlignCenter", "Toggle Format", "ColorBlack", "FontSecondary") in ops

def test_simulation_modal_open_keys():
    model = {
        "format": 0, "life": 40, "poison": 0, "cmdr_dmg": [0, 0, 0],
        "life_delta": 0, "focus": 0, "edit_mode": False, "modal_open": True, "modal_selection": 1
    }
    c = simulate_render(model)
    ops = c.operations
    assert ("draw_rbox", 14, 14, 100, 36, 3, "ColorWhite") in ops
    assert ("draw_str_aligned", 64, 26, "AlignCenter", "AlignCenter", "Reset Match", "ColorBlack", "FontSecondary") in ops
    assert ("draw_str_aligned", 64, 38, "AlignCenter", "AlignCenter", "> Toggle Format <", "ColorBlack", "FontSecondary") in ops

@pytest.mark.parametrize("focus_id, cell_x, cell_tag", [
    (2, 32, "C1:25"),
    (3, 64, "C2:22"),
    (4, 96, "C3:30"),
])
def test_simulation_cmdr_focused_and_lethal(focus_id, cell_x, cell_tag):
    model = {
        "format": 0, "life": 20, "poison": 0, "cmdr_dmg": [25, 22, 30],
        "life_delta": 0, "focus": focus_id, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    assert ("draw_box", cell_x, 45, 32, 10, "ColorBlack") in ops
    assert ("draw_frame", cell_x + 1, 46, 30, 8, "ColorWhite") in ops
    assert ("draw_str_aligned", cell_x + 16, 50, "AlignCenter", "AlignCenter", cell_tag, "ColorWhite", "FontSecondary") in ops

def test_simulation_multi_lethal_all_columns():
    model = {
        "format": 0, "life": -5, "poison": 15, "cmdr_dmg": [21, 22, 23],
        "life_delta": -5, "focus": 0, "edit_mode": False, "dialog_open": False, "dialog_selection": 0
    }
    c = simulate_render(model)
    ops = c.operations
    # All 4 aux cells are lethal, unfocused: each has black frame
    assert ("draw_frame", 1, 46, 30, 8, "ColorBlack") in ops
    assert ("draw_frame", 33, 46, 30, 8, "ColorBlack") in ops
    assert ("draw_frame", 65, 46, 30, 8, "ColorBlack") in ops
    assert ("draw_frame", 97, 46, 30, 8, "ColorBlack") in ops



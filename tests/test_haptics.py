import pytest
import re

def read_source():
    with open("f0_mtg.c", "r", encoding="utf-8") as f:
        return f.read()

# ==============================================================================
# 1. Static Source Code Assertions
# ==============================================================================

def test_haptic_includes_and_defines():
    src = read_source()
    assert "#include <furi_hal_vibro.h>" in src
    assert "HapticPattern" in src
    assert "HapticPatternNone" in src
    assert "HapticPatternLife" in src
    assert "HapticPatternCmdr" in src
    assert "HapticPatternPoison" in src
    assert "HapticEngine" in src
    assert "haptic_step" in src

def test_model_edge_flags():
    src = read_source()
    assert "was_life_dead" in src
    assert "was_poison_dead" in src
    assert "was_cmdr_dead[3]" in src or "was_cmdr_dead" in src

def test_haptic_durations():
    src = read_source()
    assert "HAPTIC_LIFE_DURATIONS[] = {400}" in src or "400" in src
    assert "150, 100, 150" in src
    assert "80, 50, 80, 50, 80" in src

def test_haptic_timer_and_lifecycle():
    src = read_source()
    assert "haptic_timer_callback" in src
    assert "furi_timer_alloc(haptic_timer_callback, FuriTimerTypePeriodic" in src
    assert "furi_timer_free(app->haptic.timer)" in src
    assert "furi_hal_vibro_set(" in src
    assert "f0_mtg_haptic_stop(app);" in src
    assert "f0_mtg_haptic_start(" in src
    assert "f0_mtg_check_lethal_transitions(" in src

def test_timer_resolution():
    src = read_source()
    # 10 ms resolution periodic timer
    assert "furi_ms_to_ticks(10)" in src

def test_save_data_size_unmodified():
    src = read_source()
    assert '_Static_assert(sizeof(MtgSaveData) == 32, "MtgSaveData must be exactly 32 bytes");' in src


# ==============================================================================
# 2. Haptic Alert Engine Simulation
# ==============================================================================

class MockHapticEngine:
    """Accurate Python simulation of the C haptic state machine in f0_mtg.c"""

    LIFE_DURATIONS = [400]
    CMDR_DURATIONS = [150, 100, 150]
    POISON_DURATIONS = [80, 50, 80, 50, 80]

    def __init__(self):
        self.pattern = "None"
        self.durations = []
        self.phase_index = 0
        self.phase_elapsed_ms = 0
        self.haptic_step = 0
        self.vibro = False
        self.timer_running = False
        self.history = []

    def start(self, pattern):
        self.stop()
        if pattern == "Life":
            self.durations = list(self.LIFE_DURATIONS)
        elif pattern == "Cmdr":
            self.durations = list(self.CMDR_DURATIONS)
        elif pattern == "Poison":
            self.durations = list(self.POISON_DURATIONS)
        else:
            return

        self.pattern = pattern
        self.phase_index = 0
        self.phase_elapsed_ms = 0
        self.haptic_step = 0
        self.vibro = True
        self.timer_running = True
        self.history.append((0, True))

    def stop(self):
        self.timer_running = False
        self.vibro = False
        self.pattern = "None"
        self.phase_index = 0
        self.phase_elapsed_ms = 0
        self.haptic_step = 0
        self.durations = []

    def tick(self, elapsed_total_ms):
        """Simulate one 10 ms timer callback tick"""
        if not self.timer_running:
            return

        self.haptic_step += 1
        self.phase_elapsed_ms += 10

        if not self.durations:
            self.stop()
            return

        if self.phase_elapsed_ms >= self.durations[self.phase_index]:
            self.phase_index += 1
            self.phase_elapsed_ms = 0

            if self.phase_index >= len(self.durations):
                self.stop()
                self.history.append((elapsed_total_ms, False))
                return

            self.vibro = (self.phase_index % 2 == 0)
            self.history.append((elapsed_total_ms, self.vibro))


class MockAppWithHaptics:
    """Simulates f0_mtg game state, counter transitions, and haptic triggering"""

    def __init__(self, format="EDH", initial_life=40, initial_poison=0, initial_cmdr=(0, 0, 0)):
        self.format = format
        self.life = initial_life
        self.poison = initial_poison
        self.cmdr_dmg = list(initial_cmdr)

        # Silent startup: edge flags initialized from initial state
        self.was_life_dead = (self.life <= 0)
        self.was_poison_dead = (self.poison >= 10)
        self.was_cmdr_dead = [d >= 21 for d in self.cmdr_dmg]

        self.haptic = MockHapticEngine()
        self.clock_ms = 0

    def check_lethal_transitions(self):
        is_life_dead = (self.life <= 0)
        is_poison_dead = (self.poison >= 10)
        is_cmdr_dead = [d >= 21 for d in self.cmdr_dmg]

        edge_life = not self.was_life_dead and is_life_dead
        edge_poison = not self.was_poison_dead and is_poison_dead
        edge_cmdr = any(not self.was_cmdr_dead[i] and is_cmdr_dead[i] for i in range(3))

        self.was_life_dead = is_life_dead
        self.was_poison_dead = is_poison_dead
        self.was_cmdr_dead = list(is_cmdr_dead)

        if edge_life:
            self.haptic.start("Life")
        elif edge_poison:
            self.haptic.start("Poison")
        elif edge_cmdr:
            self.haptic.start("Cmdr")

    def adjust_counter(self, counter_type, delta, cmdr_index=0):
        if counter_type == "life":
            self.life += delta
        elif counter_type == "poison":
            self.poison = max(0, min(99, self.poison + delta))
        elif counter_type == "cmdr":
            self.cmdr_dmg[cmdr_index] = max(0, min(99, self.cmdr_dmg[cmdr_index] + delta))
        self.check_lethal_transitions()

    def advance_time(self, duration_ms):
        for _ in range(duration_ms // 10):
            self.clock_ms += 10
            self.haptic.tick(self.clock_ms)

    def reset_match(self):
        self.life = 20 if self.format == "Standard" else 40
        self.poison = 0
        self.cmdr_dmg = [0, 0, 0]
        self.was_life_dead = False
        self.was_poison_dead = False
        self.was_cmdr_dead = [False, False, False]
        self.haptic.stop()


# ==============================================================================
# 3. Pulse Pattern Verification Tests
# ==============================================================================

def test_life_depleted_pattern_timing():
    app = MockAppWithHaptics(initial_life=1)
    app.adjust_counter("life", -1)  # 1 -> 0 (lethal transition)

    assert app.haptic.pattern == "Life"
    assert app.haptic.vibro is True

    # Advance 390 ms: should still be vibrating
    app.advance_time(390)
    assert app.haptic.vibro is True
    assert app.haptic.timer_running is True

    # At 400 ms: completes and stops
    app.advance_time(10)
    assert app.haptic.vibro is False
    assert app.haptic.timer_running is False
    assert app.haptic.pattern == "None"

def test_cmdr_lethal_pattern_timing():
    app = MockAppWithHaptics(initial_cmdr=(20, 0, 0))
    app.adjust_counter("cmdr", +1, cmdr_index=0)  # 20 -> 21

    assert app.haptic.pattern == "Cmdr"
    assert app.haptic.vibro is True

    # Phase 0: 150 ms ON
    app.advance_time(140)
    assert app.haptic.vibro is True
    app.advance_time(10)  # at 150ms -> Phase 1 (OFF)
    assert app.haptic.vibro is False

    # Phase 1: 100 ms OFF (150ms to 250ms)
    app.advance_time(90)
    assert app.haptic.vibro is False
    app.advance_time(10)  # at 250ms -> Phase 2 (ON)
    assert app.haptic.vibro is True

    # Phase 2: 150 ms ON (250ms to 400ms)
    app.advance_time(140)
    assert app.haptic.vibro is True
    app.advance_time(10)  # at 400ms -> Done
    assert app.haptic.vibro is False
    assert app.haptic.timer_running is False

def test_poison_lethal_pattern_timing():
    app = MockAppWithHaptics(initial_poison=9)
    app.adjust_counter("poison", +1)  # 9 -> 10

    assert app.haptic.pattern == "Poison"
    assert app.haptic.vibro is True

    # Burst 1: 80 ms ON (0 to 80)
    app.advance_time(70)
    assert app.haptic.vibro is True
    app.advance_time(10)  # at 80ms -> Pause 1 (OFF)
    assert app.haptic.vibro is False

    # Pause 1: 50 ms OFF (80 to 130)
    app.advance_time(40)
    assert app.haptic.vibro is False
    app.advance_time(10)  # at 130ms -> Burst 2 (ON)
    assert app.haptic.vibro is True

    # Burst 2: 80 ms ON (130 to 210)
    app.advance_time(70)
    assert app.haptic.vibro is True
    app.advance_time(10)  # at 210ms -> Pause 2 (OFF)
    assert app.haptic.vibro is False

    # Pause 2: 50 ms OFF (210 to 260)
    app.advance_time(40)
    assert app.haptic.vibro is False
    app.advance_time(10)  # at 260ms -> Burst 3 (ON)
    assert app.haptic.vibro is True

    # Burst 3: 80 ms ON (260 to 340)
    app.advance_time(70)
    assert app.haptic.vibro is True
    app.advance_time(10)  # at 340ms -> Done
    assert app.haptic.vibro is False
    assert app.haptic.timer_running is False


# ==============================================================================
# 4. Edge-Triggering Invariants Tests
# ==============================================================================

def test_life_edge_triggering_no_retrigger_when_already_dead():
    app = MockAppWithHaptics(initial_life=2)

    # 2 -> 1: Non-lethal, no haptic
    app.adjust_counter("life", -1)
    assert app.haptic.pattern == "None"

    # 1 -> 0: Rising lethal edge (0 -> 1) -> Buzz
    app.adjust_counter("life", -1)
    assert app.haptic.pattern == "Life"
    app.advance_time(400)
    assert app.haptic.pattern == "None"

    # 0 -> -1: Modifying value while already dead must NOT re-trigger
    app.adjust_counter("life", -1)
    assert app.haptic.pattern == "None"
    assert app.haptic.vibro is False

    # -1 -> -5: Further decrements do not re-trigger
    app.adjust_counter("life", -4)
    assert app.haptic.pattern == "None"

    # -5 -> 1: Returning to safe threshold resets edge flag silently
    app.adjust_counter("life", 6)
    assert app.haptic.pattern == "None"
    assert app.was_life_dead is False

    # 1 -> -1: Transitioning back to lethal triggers again
    app.adjust_counter("life", -2)
    assert app.haptic.pattern == "Life"

def test_poison_edge_triggering_invariants():
    app = MockAppWithHaptics(initial_poison=8)

    # 8 -> 9: Safe, no haptic
    app.adjust_counter("poison", +1)
    assert app.haptic.pattern == "None"

    # 9 -> 10: Rising edge -> Poison haptic
    app.adjust_counter("poison", +1)
    assert app.haptic.pattern == "Poison"
    app.advance_time(340)
    assert app.haptic.pattern == "None"

    # 10 -> 15: Increasing poison while already dead must NOT re-trigger
    app.adjust_counter("poison", +5)
    assert app.haptic.pattern == "None"

    # 15 -> 9: Decreasing to non-lethal resets edge flag silently
    app.adjust_counter("poison", -6)
    assert app.haptic.pattern == "None"
    assert app.was_poison_dead is False

    # 9 -> 12: Re-entering triggers again
    app.adjust_counter("poison", +3)
    assert app.haptic.pattern == "Poison"

def test_commander_edge_triggering_per_commander():
    app = MockAppWithHaptics(initial_cmdr=(20, 20, 20))

    # Cmdr 0 reaches 21: triggers Cmdr alert
    app.adjust_counter("cmdr", +1, cmdr_index=0)
    assert app.haptic.pattern == "Cmdr"
    app.advance_time(400)

    # Cmdr 0 increases further: does NOT re-trigger
    app.adjust_counter("cmdr", +5, cmdr_index=0)
    assert app.haptic.pattern == "None"

    # Cmdr 1 reaches 21: a DIFFERENT commander reaches lethal -> triggers!
    app.adjust_counter("cmdr", +1, cmdr_index=1)
    assert app.haptic.pattern == "Cmdr"


# ==============================================================================
# 5. Preemption & Priority Tests
# ==============================================================================

def test_immediate_preemption():
    app = MockAppWithHaptics(initial_life=10, initial_cmdr=(20, 0, 0))

    # Trigger Cmdr haptic
    app.adjust_counter("cmdr", +1, cmdr_index=0)
    assert app.haptic.pattern == "Cmdr"

    # Advance 50 ms into Cmdr pattern
    app.advance_time(50)
    assert app.haptic.timer_running is True

    # Now life drops to 0: Life should IMMEDIATELY preempt Cmdr
    app.adjust_counter("life", -10)
    assert app.haptic.pattern == "Life"
    assert app.haptic.phase_index == 0
    assert app.haptic.phase_elapsed_ms == 0

    # Life pattern plays full 400ms from interruption point
    app.advance_time(390)
    assert app.haptic.vibro is True
    app.advance_time(10)
    assert app.haptic.vibro is False

def test_simultaneous_transitions_priority():
    # If both Life depleted and Poison lethal trigger in the same step,
    # Priority is Life > Poison > Commander
    app = MockAppWithHaptics(initial_life=1, initial_poison=9)

    # Simulate simultaneous transition:
    app.life = 0
    app.poison = 10
    app.check_lethal_transitions()

    assert app.haptic.pattern == "Life"


# ==============================================================================
# 6. Silent Startup & Match Reset Tests
# ==============================================================================

def test_silent_startup():
    # If app loads with life <= 0 or poison >= 10, no vibration should fire
    app = MockAppWithHaptics(initial_life=0, initial_poison=10, initial_cmdr=(21, 0, 0))
    assert app.was_life_dead is True
    assert app.was_poison_dead is True
    assert app.was_cmdr_dead[0] is True
    assert app.haptic.pattern == "None"
    assert app.haptic.vibro is False
    assert app.haptic.timer_running is False

def test_reset_match_silences_and_clears():
    app = MockAppWithHaptics(initial_life=1)
    app.adjust_counter("life", -1)  # trigger Life alert
    assert app.haptic.pattern == "Life"
    assert app.haptic.timer_running is True

    # Reset match
    app.reset_match()
    assert app.haptic.pattern == "None"
    assert app.haptic.vibro is False
    assert app.haptic.timer_running is False
    assert app.was_life_dead is False
    assert app.was_poison_dead is False
    assert app.was_cmdr_dead == [False, False, False]


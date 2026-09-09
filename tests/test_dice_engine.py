import re
import pytest

def read_header():
    with open("mtg_dice.h", "r", encoding="utf-8") as f:
        return f.read()

def read_source():
    with open("mtg_dice.c", "r", encoding="utf-8") as f:
        return f.read()

UINT32_MAX = 0xFFFFFFFF

# ==============================================================================
# 1. Static Source Code & Contract Assertions
# ==============================================================================

def test_source_includes_and_headers():
    src = read_source()
    hdr = read_header()

    # Must include <furi_hal_random.h> for hardware entropy
    assert "#include <furi_hal_random.h>" in src
    assert '#include "mtg_dice.h"' in src

    # Standard headers in mtg_dice.h
    assert "#include <stdint.h>" in hdr
    assert "#include <stdbool.h>" in hdr
    assert "#include <stddef.h>" in hdr

def test_enum_definitions():
    hdr = read_header()

    # MtgDieType enum
    assert "MtgDieTypeCoin" in hdr
    assert "MtgDieTypeD6" in hdr
    assert "MtgDieTypeD20" in hdr
    assert "MtgDieTypePlanar" in hdr

    # MtgPlanarResult enum
    assert "PLANAR_BLANK" in hdr
    assert "PLANAR_PLANESWALK" in hdr
    assert "PLANAR_CHAOS" in hdr

    # Coin constants
    assert "MTG_COIN_TAILS 1" in hdr
    assert "MTG_COIN_HEADS 2" in hdr

def test_struct_and_macro_definitions():
    hdr = read_header()

    assert "#define MTG_DIE_TUMBLE_TICKS 16" in hdr
    assert "typedef struct" in hdr
    assert "MtgDieState" in hdr

    # Required fields in MtgDieState
    for field in [
        "MtgDieType type",
        "uint8_t target_value",
        "uint8_t current_value",
        "MtgPlanarResult target_planar",
        "MtgPlanarResult current_planar",
        "uint8_t remaining_ticks",
        "bool is_rolling",
        "uint8_t tumble_values[MTG_DIE_TUMBLE_TICKS]",
    ]:
        assert field in hdr

def test_function_declarations():
    hdr = read_header()

    assert "void mtg_dice_set_rng_source(" in hdr
    assert "uint32_t mtg_random_roll_dice(uint32_t sides);" in hdr
    assert "void mtg_die_roll(MtgDieType type, MtgDieState* state);" in hdr
    assert "bool mtg_die_step_tick(MtgDieState* state);" in hdr
    assert "MtgPlanarResult mtg_die_to_planar_result(uint8_t val);" in hdr
    assert "const char* mtg_die_type_name(MtgDieType type);" in hdr
    assert "const char* mtg_planar_result_name(MtgPlanarResult result);" in hdr
    assert "const char* mtg_coin_result_name(uint8_t coin_val);" in hdr

def test_rejection_sampling_contract():
    src = read_source()

    # Must calculate limit = UINT32_MAX - (UINT32_MAX % sides)
    assert "UINT32_MAX - (UINT32_MAX % sides)" in src

    # Discard values >= limit
    assert "raw >= limit" in src

    # Guard against divide-by-zero
    assert "if(sides == 0)" in src
    assert "return 0;" in src

    # Modulo offset to 1-indexed range
    assert "(raw % sides) + 1" in src

def test_zero_dynamic_memory_allocation():
    src = read_source()
    hdr = read_header()

    assert "malloc" not in src
    assert "free" not in src
    assert "calloc" not in src
    assert "realloc" not in src
    assert "malloc" not in hdr
    assert "free" not in hdr


# ==============================================================================
# 2. Python Simulation of C Dice Engine
# ==============================================================================

class MtgDieType:
    Coin = 0
    D6 = 1
    D20 = 2
    Planar = 3

class MtgPlanarResult:
    BLANK = 0
    PLANESWALK = 1
    CHAOS = 2

class MtgDieStateSim:
    def __init__(self):
        self.type = MtgDieType.D6
        self.target_value = 0
        self.current_value = 0
        self.target_planar = MtgPlanarResult.BLANK
        self.current_planar = MtgPlanarResult.BLANK
        self.remaining_ticks = 0
        self.is_rolling = False
        self.tumble_values = [0] * 16

class MtgDiceEngineSim:
    def __init__(self, entropy_stream=None):
        self.entropy_stream = list(entropy_stream) if entropy_stream is not None else []
        self.entropy_idx = 0
        self.rejection_count = 0

    def get_entropy(self):
        if self.entropy_idx < len(self.entropy_stream):
            val = self.entropy_stream[self.entropy_idx]
            self.entropy_idx += 1
            return val & 0xFFFFFFFF
        import random
        return random.randint(0, UINT32_MAX)

    def random_roll_dice(self, sides):
        if sides == 0:
            return 0
        if sides == 1:
            return 1

        limit = UINT32_MAX - (UINT32_MAX % sides)
        while True:
            raw = self.get_entropy()
            if raw < limit:
                return (raw % sides) + 1
            self.rejection_count += 1

    @staticmethod
    def to_planar_result(val):
        if val == 5:
            return MtgPlanarResult.PLANESWALK
        elif val == 6:
            return MtgPlanarResult.CHAOS
        return MtgPlanarResult.BLANK

    @staticmethod
    def die_type_name(die_type):
        return {
            MtgDieType.Coin: "Coin",
            MtgDieType.D6: "D6",
            MtgDieType.D20: "D20",
            MtgDieType.Planar: "Planar",
        }.get(die_type, "Unknown")

    @staticmethod
    def planar_result_name(result):
        return {
            MtgPlanarResult.BLANK: "Blank",
            MtgPlanarResult.PLANESWALK: "Planeswalk",
            MtgPlanarResult.CHAOS: "Chaos",
        }.get(result, "Unknown")

    @staticmethod
    def coin_result_name(coin_val):
        return {
            1: "Tails",
            2: "Heads",
        }.get(coin_val, "Unknown")

    def die_roll(self, die_type, state):
        if state is None:
            return

        sides = 6
        if die_type == MtgDieType.Coin:
            sides = 2
        elif die_type in (MtgDieType.D6, MtgDieType.Planar):
            sides = 6
        elif die_type == MtgDieType.D20:
            sides = 20

        state.type = die_type
        for i in range(16):
            state.tumble_values[i] = self.random_roll_dice(sides)
        state.target_value = self.random_roll_dice(sides)
        state.target_planar = self.to_planar_result(state.target_value)

        state.remaining_ticks = 16
        state.is_rolling = True
        state.current_value = state.tumble_values[0]
        state.current_planar = self.to_planar_result(state.current_value)

    def die_step_tick(self, state):
        if state is None or not state.is_rolling:
            return False

        if state.remaining_ticks > 0:
            state.remaining_ticks -= 1

        if state.remaining_ticks > 0:
            idx = 16 - state.remaining_ticks
            state.current_value = state.tumble_values[idx]
            state.current_planar = self.to_planar_result(state.current_value)
            return True
        else:
            state.current_value = state.target_value
            state.current_planar = state.target_planar
            state.is_rolling = False
            return False


# ==============================================================================
# 3. Behavioral and Edge-Case Tests
# ==============================================================================

def test_divide_by_zero_protection():
    engine = MtgDiceEngineSim()
    assert engine.random_roll_dice(0) == 0

def test_single_sided_die():
    engine = MtgDiceEngineSim()
    assert engine.random_roll_dice(1) == 1

def test_rejection_sampling_exact_boundaries():
    # sides = 6:
    # UINT32_MAX = 4294967295
    # 4294967295 % 6 = 3
    # limit = 4294967292
    # Values 4294967292, 4294967293, 4294967294, 4294967295 must be rejected
    entropy = [
        4294967292, # Rejected
        4294967295, # Rejected
        4294967291, # Accepted: 4294967291 % 6 = 5 -> roll is 6
    ]
    engine = MtgDiceEngineSim(entropy)
    roll = engine.random_roll_dice(6)
    assert roll == 6
    assert engine.rejection_count == 2

def test_coin_rejection_sampling():
    # sides = 2:
    # 4294967295 % 2 = 1
    # limit = 4294967294
    # 4294967294 and 4294967295 must be rejected
    entropy = [
        4294967294, # Rejected
        4294967295, # Rejected
        0,          # Accepted: 0 % 2 = 0 -> roll is 1 (Tails)
        1,          # Accepted: 1 % 2 = 1 -> roll is 2 (Heads)
    ]
    engine = MtgDiceEngineSim(entropy)
    assert engine.random_roll_dice(2) == 1
    assert engine.random_roll_dice(2) == 2
    assert engine.rejection_count == 2

def test_d20_rejection_sampling():
    # sides = 20:
    # 4294967295 % 20 = 15
    # limit = 4294967280
    entropy = [
        4294967280, # Rejected (exact limit)
        4294967290, # Rejected
        4294967279, # Accepted: 4294967279 % 20 = 19 -> roll is 20
    ]
    engine = MtgDiceEngineSim(entropy)
    assert engine.random_roll_dice(20) == 20
    assert engine.rejection_count == 2

def test_planar_result_mappings():
    engine = MtgDiceEngineSim()
    # 1 to 4 -> PLANAR_BLANK
    for v in [1, 2, 3, 4]:
        assert engine.to_planar_result(v) == MtgPlanarResult.BLANK
        assert engine.planar_result_name(engine.to_planar_result(v)) == "Blank"

    # 5 -> PLANAR_PLANESWALK
    assert engine.to_planar_result(5) == MtgPlanarResult.PLANESWALK
    assert engine.planar_result_name(engine.to_planar_result(5)) == "Planeswalk"

    # 6 -> PLANAR_CHAOS
    assert engine.to_planar_result(6) == MtgPlanarResult.CHAOS
    assert engine.planar_result_name(engine.to_planar_result(6)) == "Chaos"

    # Out of range fallback to BLANK
    assert engine.to_planar_result(0) == MtgPlanarResult.BLANK
    assert engine.to_planar_result(7) == MtgPlanarResult.BLANK

def test_coin_result_names():
    engine = MtgDiceEngineSim()
    assert engine.coin_result_name(1) == "Tails"
    assert engine.coin_result_name(2) == "Heads"
    assert engine.coin_result_name(0) == "Unknown"
    assert engine.coin_result_name(3) == "Unknown"

def test_die_type_names():
    engine = MtgDiceEngineSim()
    assert engine.die_type_name(MtgDieType.Coin) == "Coin"
    assert engine.die_type_name(MtgDieType.D6) == "D6"
    assert engine.die_type_name(MtgDieType.D20) == "D20"
    assert engine.die_type_name(MtgDieType.Planar) == "Planar"
    assert engine.die_type_name(99) == "Unknown"

def test_die_roll_animation_lifecycle():
    # Provide fixed predictable values for 16 tumble frames + 1 target
    tumble_sequence = [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 1, 2, 3, 4]
    target_value = 6
    # Entropy: each value - 1 so (val % 6) + 1 yields the desired value
    entropy = [v - 1 for v in tumble_sequence] + [target_value - 1]

    engine = MtgDiceEngineSim(entropy)
    state = MtgDieStateSim()

    engine.die_roll(MtgDieType.D6, state)

    assert state.is_rolling is True
    assert state.remaining_ticks == 16
    assert state.target_value == 6
    assert state.tumble_values == tumble_sequence
    assert state.current_value == tumble_sequence[0]

    # Step through ticks 1 to 15 (idx 1 to 15)
    for tick in range(1, 16):
        is_still_rolling = engine.die_step_tick(state)
        assert is_still_rolling is True
        assert state.is_rolling is True
        assert state.remaining_ticks == 16 - tick
        assert state.current_value == tumble_sequence[tick]

    # Tick 16: settles into target result
    is_still_rolling = engine.die_step_tick(state)
    assert is_still_rolling is False
    assert state.is_rolling is False
    assert state.remaining_ticks == 0
    assert state.current_value == target_value

    # Subsequent tick calls do nothing and return False
    assert engine.die_step_tick(state) is False
    assert state.current_value == target_value
    assert state.is_rolling is False

def test_planar_roll_animation_lifecycle():
    # Test planar roll updates current_planar and target_planar throughout
    tumble_sequence = [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 1, 2, 3, 4]
    target_value = 5 # Planeswalk
    entropy = [v - 1 for v in tumble_sequence] + [target_value - 1]

    engine = MtgDiceEngineSim(entropy)
    state = MtgDieStateSim()

    engine.die_roll(MtgDieType.Planar, state)
    assert state.current_planar == MtgPlanarResult.BLANK
    assert state.target_planar == MtgPlanarResult.PLANESWALK

    # Advance to tick index 4 (value 5 -> Planeswalk)
    for _ in range(4):
        engine.die_step_tick(state)
    assert state.current_value == 5
    assert state.current_planar == MtgPlanarResult.PLANESWALK

    # Advance to tick index 5 (value 6 -> Chaos)
    engine.die_step_tick(state)
    assert state.current_value == 6
    assert state.current_planar == MtgPlanarResult.CHAOS

    # Settle to final
    while state.is_rolling:
        engine.die_step_tick(state)

    assert state.current_value == 5
    assert state.current_planar == MtgPlanarResult.PLANESWALK

def test_null_state_safety():
    engine = MtgDiceEngineSim()
    # Ensure no exception on None state
    engine.die_roll(MtgDieType.D6, None)
    assert engine.die_step_tick(None) is False

def test_statistical_distribution_uniformity():
    # Statistical verification of rejection sampling uniformity
    # Roll D6 60,000 times: expected 10,000 per face
    import random
    random.seed(42)

    engine = MtgDiceEngineSim()
    counts = {i: 0 for i in range(1, 7)}
    n_rolls = 60000

    for _ in range(n_rolls):
        res = engine.random_roll_dice(6)
        counts[res] += 1

    expected = n_rolls / 6.0
    # Chi-square statistic: sum((observed - expected)^2 / expected)
    # Critical value for 5 degrees of freedom at p=0.01 is 15.086
    chi2 = sum((obs - expected) ** 2 / expected for obs in counts.values())
    assert chi2 < 15.086, f"Chi-squared statistic {chi2} indicates potential distribution bias!"

def test_coin_statistical_distribution():
    import random
    random.seed(1337)

    engine = MtgDiceEngineSim()
    counts = {1: 0, 2: 0}
    n_rolls = 40000

    for _ in range(n_rolls):
        res = engine.random_roll_dice(2)
        counts[res] += 1

    expected = n_rolls / 2.0
    # Critical value for 1 degree of freedom at p=0.01 is 6.635
    chi2 = sum((obs - expected) ** 2 / expected for obs in counts.values())
    assert chi2 < 6.635, f"Coin Chi-squared statistic {chi2} indicates potential distribution bias!"


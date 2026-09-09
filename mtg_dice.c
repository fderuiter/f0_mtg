#include "mtg_dice.h"

#ifdef HOST_TEST
/* Host test environment: furi_hal_random_get can be mocked or resolved by test harness */
#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak)) uint32_t furi_hal_random_get(void) {
    return 0;
}
#else
extern uint32_t furi_hal_random_get(void);
#endif
#else
#include <furi_hal_random.h>
#endif

static uint32_t (*s_rng_provider)(void) = NULL;

void mtg_dice_set_rng_source(uint32_t (*source)(void)) {
    s_rng_provider = source;
}

static inline uint32_t mtg_get_entropy(void) {
    if(s_rng_provider != NULL) {
        return s_rng_provider();
    }
    return furi_hal_random_get();
}

uint32_t mtg_random_roll_dice(uint32_t sides) {
    if(sides == 0) {
        return 0;
    }
    if(sides == 1) {
        return 1;
    }

    uint32_t limit = UINT32_MAX - (UINT32_MAX % sides);
    uint32_t raw;

    do {
        raw = mtg_get_entropy();
    } while(raw >= limit);

    return (raw % sides) + 1;
}

void mtg_die_roll(MtgDieType type, MtgDieState* state) {
    if(!state) {
        return;
    }

    uint32_t sides = 6;
    switch(type) {
    case MtgDieTypeCoin:
        sides = 2;
        break;
    case MtgDieTypeD6:
    case MtgDieTypePlanar:
        sides = 6;
        break;
    case MtgDieTypeD20:
        sides = 20;
        break;
    default:
        sides = 6;
        break;
    }

    state->type = type;
    for(size_t i = 0; i < MTG_DIE_TUMBLE_TICKS; ++i) {
        state->tumble_values[i] = (uint8_t)mtg_random_roll_dice(sides);
    }
    state->target_value = (uint8_t)mtg_random_roll_dice(sides);
    state->target_planar = mtg_die_to_planar_result(state->target_value);

    state->remaining_ticks = MTG_DIE_TUMBLE_TICKS;
    state->is_rolling = true;
    state->current_value = state->tumble_values[0];
    state->current_planar = mtg_die_to_planar_result(state->current_value);
}

bool mtg_die_step_tick(MtgDieState* state) {
    if(!state || !state->is_rolling) {
        return false;
    }

    if(state->remaining_ticks > 0) {
        state->remaining_ticks--;
    }

    if(state->remaining_ticks > 0) {
        size_t idx = MTG_DIE_TUMBLE_TICKS - state->remaining_ticks;
        state->current_value = state->tumble_values[idx];
        state->current_planar = mtg_die_to_planar_result(state->current_value);
        return true;
    } else {
        state->current_value = state->target_value;
        state->current_planar = state->target_planar;
        state->is_rolling = false;
        return false;
    }
}

MtgPlanarResult mtg_die_to_planar_result(uint8_t val) {
    if(val == 5) {
        return PLANAR_PLANESWALK;
    } else if(val == 6) {
        return PLANAR_CHAOS;
    }
    return PLANAR_BLANK;
}

const char* mtg_die_type_name(MtgDieType type) {
    switch(type) {
    case MtgDieTypeCoin:
        return "Coin";
    case MtgDieTypeD6:
        return "D6";
    case MtgDieTypeD20:
        return "D20";
    case MtgDieTypePlanar:
        return "Planar";
    default:
        return "Unknown";
    }
}

const char* mtg_planar_result_name(MtgPlanarResult result) {
    switch(result) {
    case PLANAR_BLANK:
        return "Blank";
    case PLANAR_PLANESWALK:
        return "Planeswalk";
    case PLANAR_CHAOS:
        return "Chaos";
    default:
        return "Unknown";
    }
}

const char* mtg_coin_result_name(uint8_t coin_val) {
    switch(coin_val) {
    case MTG_COIN_TAILS:
        return "Tails";
    case MTG_COIN_HEADS:
        return "Heads";
    default:
        return "Unknown";
    }
}


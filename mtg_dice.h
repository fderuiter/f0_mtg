#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define MTG_DIE_TUMBLE_TICKS 16

#define MTG_COIN_TAILS 1
#define MTG_COIN_HEADS 2

typedef enum {
    MtgDieTypeCoin = 0,
    MtgDieTypeD6,
    MtgDieTypeD20,
    MtgDieTypePlanar,
} MtgDieType;

typedef enum {
    PLANAR_BLANK = 0,
    PLANAR_PLANESWALK,
    PLANAR_CHAOS,
} MtgPlanarResult;

typedef struct {
    MtgDieType type;
    uint8_t target_value;
    uint8_t current_value;
    MtgPlanarResult target_planar;
    MtgPlanarResult current_planar;
    uint8_t remaining_ticks;
    bool is_rolling;
    uint8_t tumble_values[MTG_DIE_TUMBLE_TICKS];
} MtgDieState;

/**
 * @brief Configure an entropy source callback.
 * 
 * When NULL, default hardware entropy provider furi_hal_random_get() is used.
 * Can be hooked in tests for deterministic simulation.
 * 
 * @param source Pointer to a function returning a 32-bit random integer, or NULL.
 */
void mtg_dice_set_rng_source(uint32_t (*source)(void));

/**
 * @brief Generate an unbiased random die roll in range [1, sides].
 * 
 * Employs rejection sampling (limit = UINT32_MAX - (UINT32_MAX % sides)) to discard
 * values that would introduce modulo bias.
 * 
 * @param sides Number of sides on the die. If sides == 0, returns 0.
 * @return Unbiased random roll in [1, sides], or 0 if sides == 0.
 */
uint32_t mtg_random_roll_dice(uint32_t sides);

/**
 * @brief Initiate a die roll with animation tumble frames.
 * 
 * Pre-populates intermediate tumble frames, computes target outcome,
 * and sets up animation state. Does not allocate any heap memory.
 * 
 * @param type Die type (Coin, D6, D20, Planar).
 * @param state Pointer to state structure to initialize.
 */
void mtg_die_roll(MtgDieType type, MtgDieState* state);

/**
 * @brief Advance the rolling animation by one tick.
 * 
 * Steps through tumble frames while remaining_ticks > 0. When remaining_ticks reaches 0,
 * transitions current_value and current_planar to their target outcomes.
 * 
 * @param state Pointer to active die state.
 * @return true if still rolling/animating, false if settled.
 */
bool mtg_die_step_tick(MtgDieState* state);

/**
 * @brief Map a 1-6 roll value to an MtgPlanarResult.
 * 
 * 1-4: PLANAR_BLANK
 * 5:   PLANAR_PLANESWALK
 * 6:   PLANAR_CHAOS
 * 
 * @param val Roll value (1-6).
 * @return MtgPlanarResult outcome.
 */
MtgPlanarResult mtg_die_to_planar_result(uint8_t val);

/**
 * @brief Return human-readable name for die type.
 */
const char* mtg_die_type_name(MtgDieType type);

/**
 * @brief Return human-readable name for planar die outcome.
 */
const char* mtg_planar_result_name(MtgPlanarResult result);

/**
 * @brief Return human-readable name for coin outcome (1 = Tails, 2 = Heads).
 */
const char* mtg_coin_result_name(uint8_t coin_val);


#include <furi.h>
#include <furi_hal_power.h>
#include <gui/gui.h>
#include <input/input.h>

#define MTG_SAVE_MAGIC   0x4D544731 /* "MTG1" */
#define MTG_SAVE_VERSION 0x01

typedef enum {
    FormatEDH = 0,
    FormatStandard = 1,
} MtgFormat;

typedef enum {
    FocusLife = 0,
    FocusPoison = 1,
    FocusCmdr1 = 2,
    FocusCmdr2 = 3,
    FocusCmdr3 = 4,
} MtgFocus;

typedef enum {
    DialogSelectReset = 0,
    DialogSelectFormat = 1,
} DialogSelection;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t version;
    uint8_t format;
    int16_t life;
    uint8_t poison;
    uint8_t cmdr_dmg[3];
    uint8_t reserved[20];
} MtgSaveData;

_Static_assert(sizeof(MtgSaveData) == 32, "MtgSaveData must be exactly 32 bytes");

typedef struct {
    MtgSaveData save_data;
    int16_t life_delta;
    uint32_t last_life_touch_tick;
    MtgFocus focus;
    MtgFocus last_aux_focus;
    bool edit_mode;
    union {
        bool dialog_open;
        bool modal_open;
    };
    union {
        uint8_t dialog_selection;
        uint8_t modal_selection;
    };
} MtgModel;

typedef enum {
    AppEventTypeInput,
    AppEventTypeTick,
    AppEventTypeSave,
} AppEventType;

typedef struct {
    AppEventType type;
    union {
        InputEvent input;
    } value;
} AppEvent;

typedef struct {
    FuriMutex* mutex;
    FuriMessageQueue* event_queue;
    Gui* gui;
    ViewPort* view_port;
    MtgModel* model;
} MtgApp;

static void f0_mtg_render_callback(Canvas* canvas, void* context) {
    furi_assert(context);
    MtgApp* app = (MtgApp*)context;

    furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);

    canvas_clear(canvas);

    /* --- Row 0: Header (Y: 0–10) --- */
    canvas_set_color(canvas, ColorBlack);
    canvas_set_font(canvas, FontSecondary);

    /* Format string: EDH [40] or STD [20] */
    const char* format_str =
        (app->model->save_data.format == FormatStandard) ? "STD [20]" : "EDH [40]";
    canvas_draw_str_aligned(canvas, 2, 5, AlignLeft, AlignCenter, format_str);

    /* Battery readout and 9x6 outline glyph */
    uint8_t battery_pct = furi_hal_power_get_pct();
    if(battery_pct > 100) {
        battery_pct = 100;
    }
    char battery_str[8];
    snprintf(battery_str, sizeof(battery_str), "%u%%", battery_pct);
    canvas_draw_str_aligned(canvas, 114, 5, AlignRight, AlignCenter, battery_str);

    /* 9x6 battery outline glyph */
    canvas_draw_frame(canvas, 117, 2, 9, 6);
    uint8_t fill_w = (battery_pct * 7 + 50) / 100;
    if(battery_pct > 0 && fill_w == 0) {
        fill_w = 1;
    }
    if(fill_w > 7) {
        fill_w = 7;
    }
    if(fill_w > 0) {
        canvas_draw_box(canvas, 118, 3, fill_w, 4);
    }

    /* Divider line across Y = 10 */
    canvas_draw_line(canvas, 0, 10, 127, 10);

    /* --- Row 1: Transient Delta Zone (Y: 11–18) --- */
    if(app->model->life_delta != 0) {
        canvas_set_font(canvas, FontSecondary);
        char delta_str[16];
        snprintf(delta_str, sizeof(delta_str), "%+d", app->model->life_delta);
        canvas_draw_str_aligned(canvas, 64, 15, AlignCenter, AlignCenter, delta_str);
    }

    /* --- Row 2: Primary Life Body (Y: 19–44) --- */
    char life_str[12];
    snprintf(life_str, sizeof(life_str), "%d", app->model->save_data.life);

    if(app->model->save_data.life <= 0) {
        /* Solid black rectangle (28, 20, 72, 24) and inverted white text */
        canvas_set_color(canvas, ColorBlack);
        canvas_draw_box(canvas, 28, 20, 72, 24);
        canvas_set_color(canvas, ColorWhite);
        canvas_set_font(canvas, FontBigNumbers);
        canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, life_str);
        canvas_set_color(canvas, ColorBlack);
    } else {
        canvas_set_color(canvas, ColorBlack);
        canvas_set_font(canvas, FontBigNumbers);
        canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, life_str);
    }

    if(app->model->focus == FocusLife) {
        canvas_set_color(canvas, ColorBlack);
        canvas_draw_frame(canvas, 24, 19, 80, 26);
    }

    /* --- Row 3: Auxiliary Counter Matrix (Y: 45–54) --- */
    struct {
        const char* fmt;
        uint8_t val;
        MtgFocus focus;
        bool is_lethal;
    } aux_cells[4] = {
        {"P:%u", app->model->save_data.poison, FocusPoison, app->model->save_data.poison >= 10},
        {"C1:%u",
         app->model->save_data.cmdr_dmg[0],
         FocusCmdr1,
         app->model->save_data.cmdr_dmg[0] >= 21},
        {"C2:%u",
         app->model->save_data.cmdr_dmg[1],
         FocusCmdr2,
         app->model->save_data.cmdr_dmg[1] >= 21},
        {"C3:%u",
         app->model->save_data.cmdr_dmg[2],
         FocusCmdr3,
         app->model->save_data.cmdr_dmg[2] >= 21},
    };

    canvas_set_font(canvas, FontSecondary);
    for(uint8_t i = 0; i < 4; i++) {
        uint8_t cell_x = i * 32;
        bool is_focused = (app->model->focus == aux_cells[i].focus);
        bool is_lethal = aux_cells[i].is_lethal;
        char cell_str[12];
        snprintf(cell_str, sizeof(cell_str), aux_cells[i].fmt, aux_cells[i].val);

        if(is_focused) {
            /* Invert cell with black box and white text */
            canvas_set_color(canvas, ColorBlack);
            canvas_draw_box(canvas, cell_x, 45, 32, 10);

            /* Contrasting frame when focused and at lethal threshold */
            if(is_lethal) {
                canvas_set_color(canvas, ColorWhite);
                canvas_draw_frame(canvas, cell_x + 1, 46, 30, 8);
            }

            canvas_set_color(canvas, ColorWhite);
            canvas_draw_str_aligned(
                canvas, cell_x + 16, 50, AlignCenter, AlignCenter, cell_str);
            canvas_set_color(canvas, ColorBlack);
        } else {
            /* 1-pixel inset border when at lethal threshold */
            if(is_lethal) {
                canvas_set_color(canvas, ColorBlack);
                canvas_draw_frame(canvas, cell_x + 1, 46, 30, 8);
            }

            canvas_set_color(canvas, ColorBlack);
            canvas_draw_str_aligned(
                canvas, cell_x + 16, 50, AlignCenter, AlignCenter, cell_str);
        }
    }

    /* Separate columns with vertical divider lines */
    canvas_set_color(canvas, ColorBlack);
    canvas_draw_line(canvas, 32, 45, 32, 54);
    canvas_draw_line(canvas, 64, 45, 64, 54);
    canvas_draw_line(canvas, 96, 45, 96, 54);

    /* --- Row 4: Navigation Bar (Y: 55–63) --- */
    canvas_set_color(canvas, ColorBlack);
    canvas_draw_box(canvas, 0, 55, 128, 9);
    canvas_set_color(canvas, ColorWhite);
    canvas_set_font(canvas, FontSecondary);
    const char* nav_text = app->model->edit_mode ?
        "[UP/DN] +/-1  [OK] Done" :
        "[< >] Select  [OK] Edit";
    canvas_draw_str_aligned(canvas, 64, 59, AlignCenter, AlignCenter, nav_text);
    canvas_set_color(canvas, ColorBlack);

    /* --- Modal Dialog --- */
    if(app->model->modal_open || app->model->dialog_open) {
        /* Centered 100x36 rounded/bordered modal clearing background */
        canvas_set_color(canvas, ColorWhite);
        canvas_draw_rbox(canvas, 14, 14, 100, 36, 3);
        canvas_set_color(canvas, ColorBlack);
        canvas_draw_rframe(canvas, 14, 14, 100, 36, 3);

        /* Selectable items centered vertically */
        canvas_set_font(canvas, FontSecondary);
        uint8_t selection = app->model->dialog_selection;
        const char* reset_str = (selection == DialogSelectReset) ?
            "> Reset Match <" :
            "Reset Match";
        const char* toggle_format_str =
            (selection == DialogSelectFormat) ?
            "> Toggle Format <" :
            "Toggle Format";

        canvas_draw_str_aligned(canvas, 64, 26, AlignCenter, AlignCenter, reset_str);
        canvas_draw_str_aligned(canvas, 64, 38, AlignCenter, AlignCenter, toggle_format_str);
    }

    furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
}

static void f0_mtg_input_callback(InputEvent* input_event, void* context) {
    furi_assert(context);
    FuriMessageQueue* queue = (FuriMessageQueue*)context;

    AppEvent event = {
        .type = AppEventTypeInput,
        .value.input = *input_event,
    };
    furi_message_queue_put(queue, &event, FuriWaitForever);
}

static MtgApp* f0_mtg_app_alloc(void) {
    MtgApp* app = malloc(sizeof(MtgApp));
    furi_assert(app);

    app->model = malloc(sizeof(MtgModel));
    furi_assert(app->model);
    memset(app->model, 0, sizeof(MtgModel));

    /* Initialize default model state */
    app->model->save_data.magic = MTG_SAVE_MAGIC;
    app->model->save_data.version = MTG_SAVE_VERSION;
    app->model->save_data.format = FormatEDH;
    app->model->save_data.life = 40;
    app->model->save_data.poison = 0;
    memset(app->model->save_data.cmdr_dmg, 0, sizeof(app->model->save_data.cmdr_dmg));
    memset(app->model->save_data.reserved, 0, sizeof(app->model->save_data.reserved));

    app->model->life_delta = 0;
    app->model->last_life_touch_tick = 0;
    app->model->focus = FocusLife;
    app->model->last_aux_focus = FocusPoison;
    app->model->edit_mode = false;
    app->model->dialog_open = false;
    app->model->dialog_selection = DialogSelectReset;

    app->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    furi_assert(app->mutex);

    app->event_queue = furi_message_queue_alloc(8, sizeof(AppEvent));
    furi_assert(app->event_queue);

    app->view_port = view_port_alloc();
    furi_assert(app->view_port);

    view_port_draw_callback_set(app->view_port, f0_mtg_render_callback, app);
    view_port_input_callback_set(app->view_port, f0_mtg_input_callback, app->event_queue);

    app->gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(app->gui, app->view_port, GuiLayerFullscreen);

    return app;
}

static void f0_mtg_app_free(MtgApp* app) {
    furi_assert(app);

    gui_remove_view_port(app->gui, app->view_port);
    furi_record_close(RECORD_GUI);

    view_port_free(app->view_port);
    furi_message_queue_free(app->event_queue);
    furi_mutex_free(app->mutex);

    free(app->model);
    free(app);
}

static void f0_mtg_reset_match(MtgModel* model) {
    int16_t starting_life = (model->save_data.format == FormatStandard) ? 20 : 40;
    model->save_data.life = starting_life;
    model->save_data.poison = 0;
    model->save_data.cmdr_dmg[0] = 0;
    model->save_data.cmdr_dmg[1] = 0;
    model->save_data.cmdr_dmg[2] = 0;
    model->life_delta = 0;
    model->focus = FocusLife;
    model->last_aux_focus = FocusPoison;
    model->modal_open = false;
}

static void f0_mtg_toggle_format(MtgModel* model) {
    model->save_data.format = (model->save_data.format == FormatEDH) ?
        FormatStandard :
        FormatEDH;
    f0_mtg_reset_match(model);
}

static void f0_mtg_cycle_focus(MtgModel* model, bool forward) {
    if(forward) {
        if(model->focus >= FocusCmdr3) {
            model->focus = FocusLife;
        } else {
            model->focus++;
        }
    } else {
        if(model->focus <= FocusLife) {
            model->focus = FocusCmdr3;
        } else {
            model->focus--;
        }
    }

    if(model->focus != FocusLife) {
        model->last_aux_focus = model->focus;
    }
}

static void f0_mtg_focus_jump(MtgModel* model) {
    if(model->focus != FocusLife) {
        model->focus = FocusLife;
    } else {
        if(model->last_aux_focus < FocusPoison || model->last_aux_focus > FocusCmdr3) {
            model->last_aux_focus = FocusPoison;
        }
        model->focus = model->last_aux_focus;
    }
}

static void f0_mtg_adjust_focused_counter(MtgModel* model, int16_t delta, uint32_t now_tick) {
    if(model->focus == FocusLife) {
        int32_t new_life = (int32_t)model->save_data.life + delta;
        if(new_life > 999) {
            new_life = 999;
        } else if(new_life < -99) {
            new_life = -99;
        }
        int16_t actual_delta = (int16_t)(new_life - model->save_data.life);
        model->save_data.life = (int16_t)new_life;
        model->life_delta += actual_delta;
        model->last_life_touch_tick = now_tick;
    } else {
        uint8_t* val_ptr = NULL;
        if(model->focus == FocusPoison) {
            val_ptr = &model->save_data.poison;
        } else if(model->focus == FocusCmdr1) {
            val_ptr = &model->save_data.cmdr_dmg[0];
        } else if(model->focus == FocusCmdr2) {
            val_ptr = &model->save_data.cmdr_dmg[1];
        } else if(model->focus == FocusCmdr3) {
            val_ptr = &model->save_data.cmdr_dmg[2];
        }

        if(val_ptr) {
            int32_t new_val = (int32_t)(*val_ptr) + delta;
            if(new_val > 99) {
                new_val = 99;
            } else if(new_val < 0) {
                new_val = 0;
            }
            *val_ptr = (uint8_t)new_val;
            /* Modifying auxiliary counters must NOT alter life_delta */
        }
    }
}

int32_t f0_mtg_app(void* p) {
    UNUSED(p);

    MtgApp* app = f0_mtg_app_alloc();

    AppEvent event;
    bool running = true;

    /* Long-press detection for KeyOk */
    uint32_t ok_press_tick = 0;
    bool ok_held = false;
    bool ok_modal_opened = false;
    bool ok_short_handled = false;

    /* Acceleration engine state for Up/Down */
    bool repeat_active = false;
    InputKey repeat_key = InputKeyUp;
    uint32_t repeat_press_start_tick = 0;
    uint32_t repeat_last_tick = 0;

    /* Handled flags to prevent double-triggering across Press and Short */
    bool modal_toggle_pressed = false;
    bool lr_pressed = false;
    bool updown_pressed = false;
    bool back_pressed = false;

    /* Tracks key that dismissed modal to prevent trailing Release/Short leakage */
    InputKey modal_dismiss_key = InputKeyMAX;

    while(running) {
        FuriStatus status = furi_message_queue_get(app->event_queue, &event, 100);

        uint32_t now = furi_get_tick();

        /* Delta clearing: 3-second inactivity timeout (thread-safe) */
        bool delta_cleared = false;
        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
        if(app->model->life_delta != 0 && (now - app->model->last_life_touch_tick >= 3000)) {
            app->model->life_delta = 0;
            delta_cleared = true;
        }
        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
        if(delta_cleared) {
            view_port_update(app->view_port);
        }

        /* Long-press detection for KeyOk: open modal via repeat or tick duration >= 1200ms */
        if(ok_held && !ok_modal_opened && (now - ok_press_tick >= 1200)) {
            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
            app->model->modal_open = true;
            app->model->dialog_selection = DialogSelectReset;
            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
            ok_modal_opened = true;
            view_port_update(app->view_port);
        }

        if(status != FuriStatusOk) {
            continue;
        }

        if(event.type == AppEventTypeInput) {
            InputEvent* input = &event.value.input;

            bool is_modal = false;
            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
            is_modal = app->model->modal_open;
            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);

            if(is_modal) {
                /* --- Modal Controls --- */
                if(input->key == InputKeyUp || input->key == InputKeyDown) {
                    if(input->type == InputTypePress) {
                        modal_toggle_pressed = true;
                        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                        app->model->dialog_selection =
                            (app->model->dialog_selection == DialogSelectReset) ?
                            DialogSelectFormat :
                            DialogSelectReset;
                        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                        view_port_update(app->view_port);
                    } else if(input->type == InputTypeShort) {
                        if(!modal_toggle_pressed) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            app->model->dialog_selection =
                                (app->model->dialog_selection == DialogSelectReset) ?
                                DialogSelectFormat :
                                DialogSelectReset;
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            view_port_update(app->view_port);
                        }
                        modal_toggle_pressed = false;
                    } else if(input->type == InputTypeRelease) {
                        modal_toggle_pressed = false;
                    }
                } else if(input->key == InputKeyOk) {
                    if(input->type == InputTypeRelease || input->type == InputTypeShort) {
                        if(ok_modal_opened) {
                            /* Consume release of the long press that opened the modal */
                            ok_modal_opened = false;
                            ok_held = false;
                            continue;
                        }
                    }
                    if(input->type == InputTypePress) {
                        modal_dismiss_key = InputKeyOk;
                        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                        if(app->model->dialog_selection == DialogSelectFormat) {
                            f0_mtg_toggle_format(app->model);
                        } else {
                            f0_mtg_reset_match(app->model);
                        }
                        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                        view_port_update(app->view_port);
                    } else if(input->type == InputTypeShort) {
                        if(modal_dismiss_key != InputKeyOk) {
                            modal_dismiss_key = InputKeyOk;
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            if(app->model->dialog_selection == DialogSelectFormat) {
                                f0_mtg_toggle_format(app->model);
                            } else {
                                f0_mtg_reset_match(app->model);
                            }
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            view_port_update(app->view_port);
                        }
                    }
                } else if(input->key == InputKeyBack) {
                    if(input->type == InputTypePress) {
                        modal_dismiss_key = InputKeyBack;
                        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                        app->model->modal_open = false;
                        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                        view_port_update(app->view_port);
                    } else if(input->type == InputTypeShort) {
                        if(modal_dismiss_key != InputKeyBack) {
                            modal_dismiss_key = InputKeyBack;
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            app->model->modal_open = false;
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            view_port_update(app->view_port);
                        }
                    }
                }
            } else {
                /* --- Main Screen Controls --- */
                if(modal_dismiss_key != InputKeyMAX) {
                    if(input->key == modal_dismiss_key) {
                        if(input->type == InputTypeRelease) {
                            continue;
                        }
                        if(input->type == InputTypeShort) {
                            modal_dismiss_key = InputKeyMAX;
                            continue;
                        }
                    }
                    modal_dismiss_key = InputKeyMAX;
                }

                if(input->key == InputKeyBack) {
                    if(input->type == InputTypePress) {
                        back_pressed = true;
                        running = false;
                    } else if(input->type == InputTypeShort) {
                        if(!back_pressed) {
                            running = false;
                        }
                        back_pressed = false;
                    } else if(input->type == InputTypeRelease) {
                        back_pressed = false;
                    }
                } else if(input->key == InputKeyLeft || input->key == InputKeyRight) {
                    if(input->type == InputTypePress) {
                        lr_pressed = true;
                        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                        f0_mtg_cycle_focus(app->model, (input->key == InputKeyRight));
                        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                        view_port_update(app->view_port);
                    } else if(input->type == InputTypeShort) {
                        if(!lr_pressed) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            f0_mtg_cycle_focus(app->model, (input->key == InputKeyRight));
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            view_port_update(app->view_port);
                        }
                        lr_pressed = false;
                    } else if(input->type == InputTypeRelease) {
                        lr_pressed = false;
                    }
                } else if(input->key == InputKeyOk) {
                    if(input->type == InputTypePress) {
                        ok_press_tick = now;
                        ok_held = true;
                        ok_modal_opened = false;
                        ok_short_handled = false;
                    } else if(input->type == InputTypeRepeat) {
                        if(!ok_modal_opened && (now - ok_press_tick >= 1200)) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            app->model->modal_open = true;
                            app->model->dialog_selection = DialogSelectReset;
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            ok_modal_opened = true;
                            view_port_update(app->view_port);
                        }
                    } else if(input->type == InputTypeRelease) {
                        ok_held = false;
                        if(!ok_modal_opened && (now - ok_press_tick < 1200)) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            f0_mtg_focus_jump(app->model);
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            ok_short_handled = true;
                            view_port_update(app->view_port);
                        }
                        ok_modal_opened = false;
                    } else if(input->type == InputTypeShort) {
                        if(!ok_modal_opened && !ok_short_handled) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            f0_mtg_focus_jump(app->model);
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            ok_short_handled = true;
                            view_port_update(app->view_port);
                        }
                    }
                } else if(input->key == InputKeyUp || input->key == InputKeyDown) {
                    int16_t dir = (input->key == InputKeyUp) ? 1 : -1;
                    if(input->type == InputTypePress) {
                        repeat_active = true;
                        repeat_key = input->key;
                        repeat_press_start_tick = now;
                        repeat_last_tick = now;
                        updown_pressed = true;

                        furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                        f0_mtg_adjust_focused_counter(app->model, dir, now);
                        furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                        view_port_update(app->view_port);
                    } else if(input->type == InputTypeRepeat) {
                        if(repeat_active && repeat_key == input->key) {
                            uint32_t hold_duration = now - repeat_press_start_tick;
                            if(hold_duration >= 400 && hold_duration <= 1400) {
                                if(now - repeat_last_tick >= 100) {
                                    furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                                    f0_mtg_adjust_focused_counter(app->model, dir, now);
                                    furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                                    repeat_last_tick = now;
                                    view_port_update(app->view_port);
                                }
                            } else if(hold_duration > 1400) {
                                if(now - repeat_last_tick >= 150) {
                                    furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                                    f0_mtg_adjust_focused_counter(app->model, dir * 5, now);
                                    furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                                    repeat_last_tick = now;
                                    view_port_update(app->view_port);
                                }
                            }
                        }
                    } else if(input->type == InputTypeRelease) {
                        if(repeat_active && repeat_key == input->key) {
                            repeat_active = false;
                        }
                        updown_pressed = false;
                    } else if(input->type == InputTypeShort) {
                        if(!updown_pressed) {
                            furi_check(furi_mutex_acquire(app->mutex, FuriWaitForever) == FuriStatusOk);
                            f0_mtg_adjust_focused_counter(app->model, dir, now);
                            furi_check(furi_mutex_release(app->mutex) == FuriStatusOk);
                            view_port_update(app->view_port);
                        }
                        updown_pressed = false;
                    }
                }
            }
        }
    }

    f0_mtg_app_free(app);

    return 0;
}


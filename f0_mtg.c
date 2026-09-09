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

int32_t f0_mtg_app(void* p) {
    UNUSED(p);

    MtgApp* app = f0_mtg_app_alloc();

    AppEvent event;
    bool running = true;

    while(running) {
        FuriStatus status = furi_message_queue_get(app->event_queue, &event, FuriWaitForever);
        if(status != FuriStatusOk) {
            continue;
        }

        if(event.type == AppEventTypeInput) {
            if(event.value.input.type == InputTypePress && event.value.input.key == InputKeyBack) {
                running = false;
            }
        }
    }

    f0_mtg_app_free(app);

    return 0;
}


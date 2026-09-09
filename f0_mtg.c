#include <furi.h>
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
    bool dialog_open;
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
    canvas_set_font(canvas, FontBigNumbers);

    char life_str[12];
    snprintf(life_str, sizeof(life_str), "%d", app->model->save_data.life);
    canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, life_str);

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


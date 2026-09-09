#include <furi.h>
#include <gui/gui.h>
#include <input/input.h>

static void f0_mtg_render_callback(Canvas* canvas, void* context) {
    UNUSED(context);

    canvas_clear(canvas);
    canvas_set_font(canvas, FontBigNumbers);
    canvas_draw_str_aligned(canvas, 64, 32, AlignCenter, AlignCenter, "40");
}

static void f0_mtg_input_callback(InputEvent* input_event, void* context) {
    furi_assert(context);
    furi_message_queue_put(context, input_event, FuriWaitForever);
}

int32_t f0_mtg_app(void* p) {
    UNUSED(p);

    FuriMessageQueue* event_queue = furi_message_queue_alloc(8, sizeof(InputEvent));
    ViewPort* view_port = view_port_alloc();
    Gui* gui = furi_record_open(RECORD_GUI);

    view_port_draw_callback_set(view_port, f0_mtg_render_callback, NULL);
    view_port_input_callback_set(view_port, f0_mtg_input_callback, event_queue);
    gui_add_view_port(gui, view_port, GuiLayerFullscreen);

    InputEvent event;
    bool running = true;

    while(running && furi_message_queue_get(event_queue, &event, FuriWaitForever) == FuriStatusOk) {
        if(event.type == InputTypePress && event.key == InputKeyBack) {
            running = false;
        }
    }

    gui_remove_view_port(gui, view_port);
    view_port_free(view_port);
    furi_message_queue_free(event_queue);
    furi_record_close(RECORD_GUI);

    return 0;
}

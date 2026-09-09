# Flipper Zero (`f0_mtg`) Development Guidelines

## Architecture & State Management
- **Event-Driven Architecture**: Use an application event wrapper (`AppEvent` with `AppEventType` and payload union) dispatched via `FuriMessageQueue` (default depth: 8) rather than raw single-purpose queues.
- **Thread Safety & Mutex Locking**: Synchronize all model reads (in `ViewPort` draw callbacks) and mutations (in event processing) using `FuriMutex`.
- **Symmetric Resource Lifecycle**: Every allocated Furi primitive (`furi_mutex_alloc`, `furi_message_queue_alloc`, `view_port_alloc`, `furi_record_open`, `malloc`) must have a corresponding symmetric deallocation (`furi_mutex_free`, `furi_message_queue_free`, `view_port_free`, `furi_record_close`, `free`) in teardown routines.

## Input Handling & State Machine Invariants
- **Modal Dismissal & Trailing Event Isolation**: When closing or dismissing a modal dialog or transitioning screen states on an `InputTypePress` event (e.g., `KeyOk` or `KeyBack`), the physical button release will subsequently emit `InputTypeRelease` and `InputTypeShort` events. Always record a dismissal sentinel (`modal_dismiss_key`) and consume trailing release and short events to prevent accidental focus jumps or app exits on the newly active view.
- **Per-Key Press Tracking**: Never use a single global `key_press_handled` flag across distinct buttons. Long holds for repeat acceleration do not emit synthetic `InputTypeShort` events upon release in Furi OS; un-scoped flags will poison subsequent inputs. Scope press flags per key or action and reset them cleanly on `InputTypeRelease`.
- **Custom Long-Press Timing**: Furi OS triggers built-in `InputTypeLong` at ~300–500 ms. For custom thresholds (e.g., > 1.2s):
  1. Record `press_start_tick` on `InputTypePress`.
  2. Evaluate elapsed duration in `InputTypeRepeat`.
  3. Also evaluate elapsed duration in the event loop's periodic queue wait timeout (e.g., 100 ms ticks) to guarantee prompt triggering even if repeat events are dropped or throttled.
  4. On `InputTypeRelease`, suppress the short press action if the custom long-press threshold was already triggered.

## Display & Canvas Constraints (128x64 Monochrome)
- **Screen Bounds**: X coordinates range from 0 to 127; Y coordinates range from 0 to 63.
- **Font Availability**:
  - `FontPrimary`: 8pt bold, full ASCII.
  - `FontSecondary`: 6–7pt standard, full ASCII.
  - `FontKeyboard`: Monospaced 5x7 glyphs.
  - `FontBigNumbers`: Large numeric display (`profont22_tn`). **Digits '0'–'9' ONLY.** Does not support `-` (minus sign) or punctuation. For negative numbers, draw custom minus lines or use a fallback font.
- **Monochrome Inversion Idiom**:
  - To render inverted (white-on-black) elements:
    1. Draw solid background with `canvas_draw_box()`.
    2. Switch color: `canvas_set_color(canvas, ColorWhite)`.
    3. Render text or frames.
    4. Reset color: `canvas_set_color(canvas, ColorBlack)`.

## Binary Save & Data Formats
- **Fixed Size & Alignment**: Binary save structs must be packed (`__attribute__((packed))`) and accompanied by a compile-time `_Static_assert(sizeof(...) == TARGET_BYTES)` assertion.
- **Magic & Versioning**: Always include a 4-byte magic identifier and a version byte at the head of binary save payloads.

## Hardware Abstraction & System Libraries
- **Power Management**: Use `<furi_hal_power.h>` for battery functions such as `furi_hal_power_get_pct()`. HAL headers are part of core firmware and do not require additions to `requires` in `application.fam`.

## Build & Verification
- **Host Tooling Check**: Do not assume `ufbt` or cross-compilers are in global PATH on Windows. Validate memory layouts and struct sizes using Python `struct` checks or native static assertions when direct `ufbt` compilation is unavailable.
- **Offline UI Simulation Testing**: Maintain Python simulation test suites (`tests/test_ui_rendering.py` with `MockCanvas`) to verify coordinate bounds, state transitions, and edge cases when building on environments without `ufbt`.

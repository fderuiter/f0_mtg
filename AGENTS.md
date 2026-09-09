# Flipper Zero (`f0_mtg`) Development Guidelines

## Architecture & State Management
- **Event-Driven Architecture**: Use an application event wrapper (`AppEvent` with `AppEventType` and payload union) dispatched via `FuriMessageQueue` (default depth: 8) rather than raw single-purpose queues.
- **Thread Safety & Mutex Locking**: Synchronize all model reads (in `ViewPort` draw callbacks) and mutations (in event processing) using `FuriMutex`.
- **Symmetric Resource Lifecycle**: Every allocated Furi primitive (`furi_mutex_alloc`, `furi_message_queue_alloc`, `view_port_alloc`, `furi_record_open`, `malloc`) must have a corresponding symmetric deallocation (`furi_mutex_free`, `furi_message_queue_free`, `view_port_free`, `furi_record_close`, `free`) in teardown routines.

## Binary Save & Data Formats
- **Fixed Size & Alignment**: Binary save structs must be packed (`__attribute__((packed))`) and accompanied by a compile-time `_Static_assert(sizeof(...) == TARGET_BYTES)` assertion.
- **Magic & Versioning**: Always include a 4-byte magic identifier and a version byte at the head of binary save payloads.

## Build & Verification
- **Host Tooling Check**: Do not assume `ufbt` or cross-compilers are in global PATH on Windows. Validate memory layouts and struct sizes using Python `struct` checks or native static assertions when direct `ufbt` compilation is unavailable.

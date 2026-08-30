# iPhone AR Game

Use Swift, SwiftUI, RealityKit, and ARKit for iPhone-first augmented-reality
games. Keep AR session, camera, anchors, tracking, and render state transient
on the device; AR session state must not be assumed to survive an interruption
or a new app launch.

Model durable player profile, progress, inventory, and completed-world state at
the persistence API boundary. Restore only the durable data that the game needs
to reconstruct its experience, then establish a new AR session on the device.

Use `xcodebuild` and XCTest as the standard build and verification entry
points. App Store signing, provisioning, and release automation require an
explicit delivery decision and are outside this stack.

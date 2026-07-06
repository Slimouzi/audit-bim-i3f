# Prompt — Viewpoint sharing / "Follow me" presenter mode in the BIMData viewer

> Task prompt to hand to a developer (or AI coding session) working on the BIMData
> viewer codebase. Written in English as requested.

---

## Prompt

You are working on the **BIMData viewer** (multi-window viewer: 3D, 2D plans from
PDF/DWG, and 360° photos). Implement a **real-time viewpoint sharing / follow
feature**, similar to Figma's "click an avatar to follow their cursor", so that a
user can present a digital model (maquette numérique) live to other users
connected to the same project on the platform.

### Context and constraint: reuse the legacy code

The codebase already contains **legacy viewer-synchronization code** (old
"shared camera" / viewer sync feature that used to broadcast the 3D camera over
the platform's websocket channel). It is outdated and only ever worked for the
3D window.

1. **Locate this legacy code first** (search for terms like `sync`, `sharedCamera`,
   `follow`, `presence`, websocket camera broadcast handlers) and summarize what
   it did and why it no longer works.
2. **Update it** to the current viewer plugin architecture and current APIs —
   do not rewrite from scratch if the transport and message plumbing can be
   salvaged.
3. **Extend it** so it works for **all model types**: 3D models, 2D plans
   (PDF and DWG), and 360° photos.

### Expected behavior

**Presence**
- Every user connected to the same space/project in the viewer appears as a
  colored avatar in the viewer header (reuse the existing presence/websocket
  connection if one exists).
- Hovering an avatar shows the user's name; each user has a stable color.

**Entering follow mode (Figma-like)**
- Clicking another user's avatar starts **following** that user (the "presenter").
- The follower's viewport mirrors the presenter's view in real time:
  - **3D window**: camera position, target/orientation, zoom, projection mode,
    active storey, section planes if cheap to include.
  - **2D window (PDF/DWG)**: current model/sheet, pan offset, zoom level, rotation.
  - **360° photos**: current photo, camera yaw/pitch, field of view.
- If the presenter **switches window or model** (e.g. opens a DWG plan, jumps to a
  360° photo), followers switch too — the same window type and model open on
  their side, then the viewpoint syncs.
- Optionally (nice to have): broadcast the presenter's **cursor position** and
  render it as a colored named cursor in followers' viewports, like Figma.

**While following**
- The follower's viewport shows a **colored border** matching the presenter's
  avatar color, with a banner: *"Following {name} — click to stop"*.
- The presenter sees an indicator: *"{n} user(s) following you"*, and the avatars
  of their followers.
- Follow mode is **read-only for navigation**: any manual interaction by the
  follower (orbit, pan, zoom, click in the viewport, window switch) immediately
  **breaks follow mode**, exactly like Figma. Clicking the avatar again resumes.
- Multiple users can follow the same presenter; follow relationships are
  one-directional (A following B does not make B follow A).

**Transport and performance**
- Reuse the platform's existing websocket channel (room scoped to
  space/project). Messages carry `{userId, windowType, modelId, viewpointState}`.
- Throttle broadcasts on the presenter side (~30–60 ms, or
  `requestAnimationFrame`-based) and interpolate/lerp on the follower side so the
  motion is smooth, not jittery.
- Send full state on follow start (so a late follower snaps to the presenter
  immediately), then deltas.

**Edge cases**
- Presenter disconnects or leaves the viewer → all followers exit follow mode
  with a small notice.
- Follower lacks access to the model/window the presenter opened → show a
  non-blocking message and pause sync until the presenter returns to an
  accessible model.
- Presenter idle: no messages sent when the viewpoint hasn't changed.
- Reconnection: on websocket reconnect, re-request the presenter's full state.

### Acceptance criteria
1. Legacy sync code identified, updated to the current viewer API, and used as
   the base of the implementation (or its removal justified in the PR).
2. Follow works in **all three viewers**: 3D, 2D (PDF and DWG), 360° photos —
   including cross-window transitions initiated by the presenter.
3. Any follower interaction breaks follow mode instantly; re-clicking the avatar
   resumes it.
4. Presenter and follower UI indicators (border, banner, follower count) present.
5. Smooth motion at ~30 fps perceived on the follower side with throttled traffic.
6. Presenter disconnect, permission-denied model, and reconnect cases handled.
7. Demo scenario: user A presents a model switching 3D → DWG plan → 360° photo
   while users B and C follow; both stay in sync end to end.

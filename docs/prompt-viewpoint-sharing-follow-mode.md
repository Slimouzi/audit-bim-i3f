# Prompt — Viewpoint sharing / "Follow me" presenter mode in the BIMData viewer

> Self-contained task prompt, to be pasted into a VS Code AI session opened on
> the viewer codebase. It carries no repository context on purpose: the prompt
> instructs the agent to discover the context from the open workspace first.

---

## Prompt

You are working in **VS Code**, with the project workspace open. Do not assume
anything about the codebase from this prompt: **derive all context from the
workspace itself** before writing any code.

### Step 0 — Discover the context from the workspace

1. Explore the open workspace: identify the viewer's architecture, the window
   types it supports (3D, 2D plans from PDF/DWG, 360° photos), the plugin
   system, and how real-time communication (websockets, presence) is wired.
2. **Locate the legacy viewer-synchronization code**: search the workspace for
   terms like `sync`, `sharedCamera`, `follow`, `presence`, or websocket
   handlers that broadcast camera state. Summarize what that old code did, why
   it is outdated, and what can be salvaged (transport, message plumbing).
3. Only then plan the implementation. **Update the legacy code rather than
   rewriting from scratch** wherever the plumbing is reusable, and align it
   with the current viewer/plugin APIs found in the workspace.

### Goal

Implement a **real-time viewpoint sharing / follow feature**, similar to
Figma's "click an avatar to follow them", so a user can present a digital
model (maquette numérique) live to other users connected to the same project.
It must work for **all model types**: 3D, 2D plans (PDF and DWG), and 360°
photos.

### Expected behavior

**Presence**
- Every user connected to the same space/project in the viewer appears as a
  colored avatar in the viewer UI (reuse the existing presence/websocket
  connection if the workspace already has one).
- Hovering an avatar shows the user's name; each user has a stable color.

**Entering follow mode (Figma-like)**
- Clicking another user's avatar starts **following** that user (the
  "presenter"). The follower's viewport mirrors the presenter's view in real
  time:
  - **3D window**: camera position, target/orientation, zoom, projection mode,
    active storey; section planes if cheap to include.
  - **2D window (PDF/DWG)**: current model/sheet, pan offset, zoom level,
    rotation.
  - **360° photos**: current photo, camera yaw/pitch, field of view.
- If the presenter **switches window or model** (e.g. opens a DWG plan, jumps
  to a 360° photo), followers switch too — the same window type and model open
  on their side, then the viewpoint syncs.
- Nice to have: broadcast the presenter's **cursor position** and render it as
  a colored named cursor in followers' viewports, like Figma.

**While following**
- The follower's viewport shows a **colored border** matching the presenter's
  avatar color, with a banner: *"Following {name} — click to stop"*.
- The presenter sees *"{n} user(s) following you"* and their followers' avatars.
- Follow mode is **read-only for navigation**: any manual interaction by the
  follower (orbit, pan, zoom, click in the viewport, window switch)
  immediately **breaks follow mode**, exactly like Figma. Clicking the avatar
  again resumes.
- Multiple users can follow the same presenter; the relationship is
  one-directional.

**Transport and performance**
- Reuse the websocket channel found in the workspace (room scoped to
  space/project). Messages carry `{userId, windowType, modelId, viewpointState}`.
- Throttle broadcasts on the presenter side (~30–60 ms or
  `requestAnimationFrame`-based) and interpolate on the follower side so the
  motion is smooth.
- Send full state on follow start (late follower snaps immediately), then
  deltas; no messages while the presenter's viewpoint is unchanged.

**Edge cases**
- Presenter disconnects or leaves → followers exit follow mode with a notice.
- Follower lacks access to the model the presenter opened → non-blocking
  message, sync paused until the presenter returns to an accessible model.
- Websocket reconnect → re-request the presenter's full state.

### Acceptance criteria
1. Legacy sync code identified in the workspace, updated to the current viewer
   API, and used as the base of the implementation (or its removal justified).
2. Follow works in **all three viewers** — 3D, 2D (PDF and DWG), 360° photos —
   including cross-window transitions initiated by the presenter.
3. Any follower interaction breaks follow mode instantly; re-clicking resumes.
4. Presenter and follower UI indicators (border, banner, follower count).
5. Smooth perceived motion on the follower side with throttled traffic.
6. Presenter disconnect, permission-denied model, and reconnect handled.
7. Demo: user A presents switching 3D → DWG plan → 360° photo while users B
   and C follow; both stay in sync end to end.

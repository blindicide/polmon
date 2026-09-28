# Topology Studio

Topology Studio is the graphical topology authoring surface in the desktop client. Open
**Topologies** and choose **Canvas** to begin from the empty `new-topology` document, or open an
existing YAML file/library item. The **YAML** tab remains available at all times; canvas operations
write ordinary topology YAML, and YAML that currently fails validation remains editable without
destroying the last valid canvas.

## Build a lab

1. Double-click **Network / switch** in the palette. The studio selects the first free `/24` in
   `192.168.230.0/24`–`192.168.240.0/24`.
2. Double-click L0 or L1 devices to place them. L2 is visible for forward-compatible documents but
   deployment remains honestly refused.
3. Select a device, choose the switch in the inspector and click **Connect**. The first free host
   address and a locally administered unicast MAC are allocated automatically.
4. Edit the normal name in the inspector. The machine-readable ID and globally stable UUID remain
   unchanged; **Copy UUID** places that UUID on the clipboard.
5. Drag devices on the infinite scene. Positions snap to the 20-pixel grid and are stored as each
   node's `layout`. Documents without layout receive a deterministic row layout.
6. Use marquee selection and Ctrl/Shift selection for multiple devices. Ctrl+C/Ctrl+V, Ctrl+D,
   Delete, Undo and Redo operate on the selection. Wheel zoom is bounded to 25–400%; **Fit to view**,
   **Zoom to selection**, and **100%** provide deterministic navigation.
7. The existing validation panel follows edits through `POST /v1/topologies/validate`; selecting a
   problem jumps to its YAML location. Offline, schema/resource validation runs locally and the
   client clearly marks backend-only actions unavailable.

## Save, import, export and deploy

**Save as** exports YAML locally. **Load** imports/upserts the normalized document into
`<data-dir>/library/topologies/<id>.yml` using an atomic replace. `PUT /v1/topologies/{id}` is the
idempotent upsert API, `GET` exports the normalized YAML, and `DELETE` removes a non-deployed entry
after client confirmation. The library is reloaded when the backend restarts, including node
layout, names and UUIDs. **Deploy** is enabled only for a locally or remotely validated document.

The canvas never asks for raw addresses, never silently widens the address profile and never
pretends L2 execution exists. A duplicate link or exhausted address pool is refused with a stable
code while the rest of the document remains editable.

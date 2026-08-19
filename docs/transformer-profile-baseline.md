# Fixed-year transformer profile baseline

The phase-one dashboard uses one precomputed 2023 PT15M baseline. Selecting a
PC6 or CBS buurt does not calculate that feature in isolation. It looks up the
feature's Grid assignments and returns the complete baseline demand and PV
production of each connected LV/MV and MV/HV transformer.

The persisted cache stores shared annual shapes and per-transformer
coefficients instead of repeating 35,040 points for every transformer:

- residential PC6 demand uses the Consumption model's accepted 2023 compact
  profile recipe and annual anchors;
- PV uses separate residential and commercial per-kWp shapes and the PV model's
  2035 capacity scenario;
- Grid's versioned PC6 reach and CBS-buurt hierarchy assignments provide the
  source shares;
- a selected feature only determines which transformer totals are returned and
  highlighted. It does not remove the other contributors.

`transformer-profile-init` validates the model identities and reuses the named
Docker volume when they are unchanged. It does not rebuild or download the Grid
model. A changed Consumption, PV, or Grid identity invalidates the baseline and
causes only this compact profile cache to be regenerated. The identity includes
the Consumption state/cache fingerprint, Grid data version, and the latest PV
capacity output ID and artifact SHA-256, not only model version labels.

## Current limitations

- Consumption's current profile calendar is 2023. PV's native reference-weather
  calendar is 2024. For this MVP, 29 February is removed and the remaining PV
  intervals are projected in order onto the fixed 2023 profile axis. This is a
  modeling alignment assumption, not an observed same-year pairing.
- The Consumption API does not yet expose a compact whole-layer recipe. The
  initializer therefore reads the accepted source-cache manifest and recipe
  from the Consumption model's read-only volume. Replace this adapter with a
  versioned model API output when that capability exists.
- Totals currently include residential PC6 demand and CBS-buurt PV production.
  EV, wind, heat, commercial and industrial profiles are excluded until those
  models publish compatible PT15M profile contracts.
- The policy-tool integration currently builds and serves this transformer
  baseline cache. In the professional architecture, ownership should move
  behind the congestion-model service API so the policy-tool backend remains
  the orchestrator rather than the calculation owner.
- The baseline is immutable. Future scenario controls should copy the cached
  transformer total and apply only the selected feature's delta.

These limitations lower the combined `datacompleetheid` to 1/3. They are
included in the API result and must remain visible in provenance when the cache
contract evolves.

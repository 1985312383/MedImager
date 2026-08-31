# MedImager v2.6 visual regression workflow

The release visual suite is defined by `default_v26_scenarios()`: seven dark
Chinese surfaces and five light English surfaces. Pixel baselines use a fixed
1280 x 800 logical viewport, DPR 1, and Segoe UI 9 on Windows. Tests must not
commit screenshots captured with a different contract.

## Capture and compare

The checked release command uses `RealMedImagerSurfaceProvider`. Every capture
root is a deterministic `VisualWorkbenchShell` containing the production
`ViewerToolbar`, production `SeriesPanel`, menu/status chrome, and one actual
StartCenter, SettingsDialog, MultiViewerGrid, or MprWorkspace. The navigator is
visible for CT, MR, MPR, reference-line, and geometry-rejection scenarios; it
is intentionally hidden on the no-study start and settings surfaces. This
covers the reading-workbench relationship rather than testing isolated central
widgets.

All image volumes, geometry, recent entries, and settings are deterministic and
in memory. The provider neither reads studies nor writes user settings. It
disables background thumbnail generation and deferred tree expansion only in
the release shell so capture timing cannot change pixels; normal SeriesPanel
construction retains both behaviors. The harness renders each whole workbench
into a DPR-controlled `QImage`; it does not inherit the monitor on which the
test happens to run.

```powershell
python -m medimager.qa.visual_release `
  --mode compare `
  --baseline-root release/visual-baselines/v2.6 `
  --artifact-root build/visual-regression/v2.6
```

Compare mode never changes the baseline. It writes `actual/*.png`, `diff/*.png`,
and `visual-report.json`. The release limits are MAE <= 2 and no more than 0.5%
of pixels with a channel delta greater than 12.

## Updating baselines

An update requires both update mode and the explicit authorization flag. The
command captures all 12 real surfaces before switching the manifest. This
prevents a normal local or CI comparison from accepting a regression.

```powershell
python -m medimager.qa.visual_release `
  --mode update `
  --allow-baseline-update `
  --baseline-root release/visual-baselines/v2.6 `
  --artifact-root build/visual-regression/v2.6
```

All captures complete before mutation begins. Images are content-addressed and
written first; `visual-baselines.json` is atomically replaced last. A failed or
cancelled capture therefore leaves the previous baseline set usable. Review the
new screenshots manually before committing them.

## 125% and 150% DPI checks

High-DPI jobs do geometry and visibility checks only. They intentionally do not
create or compare pixel baselines:

```powershell
python -m medimager.qa.visual_release `
  --visibility-only `
  --artifact-root build/visual-regression/v2.6
```

The default scale factors are 1.25 and 1.5. For a 1280 x 800 physical target,
the checks use 1024 x 640 and approximately 853 x 533 logical viewports and
write `visibility-report.json`.

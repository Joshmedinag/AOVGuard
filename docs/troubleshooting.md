# Troubleshooting

## `pip: command not found`

Use:

```powershell
python -m pip install uv
```

or install uv with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Python 3.9 is not supported

Install Python 3.12 using uv:

```powershell
uv python install 3.12
uv sync --locked --python 3.12 --extra dev
```

## The desktop interface requires the GUI extra

Base installation intentionally provides the headless CLI. Install the optional
desktop dependencies when launching the UI:

```powershell
uv run --extra gui aovguard-ui
```

For a packaged installation, install `aovguard[gui]`. OpenCV has been removed
from analyzers and tests, so `OPENCV_IO_ENABLE_OPENEXR` is no longer required.

## `No RGB AOV groups found in the EXR files`

This message belongs to the legacy multilayer command. Use the automatic
inspector to see the actual structure:

```powershell
uv run aovguard inspect-structure path\to\frame.exr
```

Try one of the following:

- check that **Merge AOVs** was enabled when exporting from Maya/Arnold;
- check whether the named layers expose identifiable R, G and B channels.

## `0 AOVs analyzed`

The automatic backend rejects a folder containing no discoverable EXRs. If the
report contains detected AOVs but zero analyzed AOVs, the file may contain only
technical, unknown or unsupported deep data. Flat multipart AOVs are analyzed
independently under namespaced identities.

## The UI freezes or seems slow

The analysis runs in a worker thread and updates a progress bar. Native EXR
reads eagerly load all part pixels and can take time on large files.
In the development checkout, keep **Isolate analysis process** enabled:
**Cancel** stops/reaps the active child even during native reads. Closing keeps
the window alive until child/thread cleanup, then closes automatically without
blocking the event loop. If isolation is disabled, cancellation is cooperative
and must wait for native I/O to return.

## `frame_timeout` or `worker_crash`

Review the exact affected file and exported `frame_execution` status/stage,
timeout and exit code. A frame timeout includes headers, decode, reductions
and IPC after worker readiness; startup has its own 30-second deadline. Check
whether the file is incomplete, storage is slow or the selected deadline is
too short. Increase `--frame-timeout-seconds` deliberately when appropriate,
or omit it for no frame deadline. The failed frame is retained and the next
frame can run in a replacement child; rerender or repair corrupt inputs.

Do not combine `--in-process` with a timeout. In-process mode cannot stop a
blocked native read and is not a workaround for files that crash the decoder.
CLI Ctrl+C during analysis cleans up the child and returns `130` without a
traceback. Process isolation is not a security sandbox or a hard memory cap.
The frame timeout does not cover folder/NFS listing, final rule evaluation,
report export or manual **Inspect Structure**, which run in the parent.

Recorded elapsed time includes service and can include startup/cleanup: a
0.1-second frame deadline can therefore coexist with a longer diagnostic
elapsed value without extending that service deadline.

## Fatal worker cleanup failure

`WorkerCleanupError` means cleanup could not confirm that a child or receiver
stopped. Unlike an ordinary frame timeout/crash, it aborts the whole job and
forbids executor reuse. The GUI blocks new analyses rather than continuing
silently. Follow the visible PID/error details to check any remaining analysis
process (for example, with Task Manager on Windows), then restart AOVGuard.
Do not terminate unrelated Python jobs. An OS-level unkillable process may
require system-level intervention; the application does not promise a hard
termination bound for that situation.

## Saved execution controls show a warning

Invalid stored isolation values restore enabled isolation. Invalid timeouts
select 30 seconds; unsupported saved ranges are adjusted visibly. Review
**Isolate analysis process** / **Frame timeout (s)** before analyzing. Fresh
and older settings default to isolation enabled and `0 / No timeout`.

## Multipart part identities change

Unique named parts use `[part:escaped-name]::AOV` while the file is multipart.
Unnamed/duplicate part names use index fallback. A two-part file becoming
single-part returns to historical unqualified keys; review the resulting
structure-change finding rather than treating it as lost image data.

## Report destination is blocked or export fails

Use distinct report paths with `.json`, `.html` or `.csv` names. Development
exports reject EXR filenames, symlink destinations, read-only files, selected
configuration/input paths and duplicate CLI output paths. A comparison must
write somewhere other than its baseline or candidate input.

For a permission or file-lock error, close the program holding the destination
or choose another writable folder, then retry export. The GUI keeps the current
analysis available. Failures before atomic replacement preserve an existing
report. If one of two exports already succeeded, it remains published.
Unexpected process termination can leave a hidden `.report-name.*.tmp` file;
check that no export is active before removing a leftover temporary file.

## Baseline configuration is incompatible

Reanalyze both inputs using matching luminance weights, thresholds, category
overrides, source interpretation and effective rules. AOVGuard refuses to
compare contradictory recorded configurations. Older analysis schemas 1.0/1.1
remain readable with a warning when provenance is insufficient; unavailable
numeric metrics are not reported as unchanged.

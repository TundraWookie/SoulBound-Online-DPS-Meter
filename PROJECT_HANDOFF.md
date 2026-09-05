# Soulbound DPS Meter — Project Handoff

Last updated: September 5, 2026  
Current public release: **v0.8.14**  
Repository: <https://github.com/TundraWookie/SoulBound-Online-DPS-Meter>  
Releases: <https://github.com/TundraWookie/SoulBound-Online-DPS-Meter/releases>

This file is the working memory for the project. Read it before changing the meter in a new chat.

## Purpose and permissions

Soulbound DPS Meter is a community overlay for **Soulbound Online**. It reads the game-provided combat-log files; it does not read game memory, inject into the game, or send data over the network.

- Creator/maintainer: **TundraWooK**.
- The Soulbound creator Tom Landon and the development team have granted permission for this community project. Combat logs were added in response to a request for a DPS meter.
- Keep the app easy for community members to use: automatic log detection, single-file downloads, and no required configuration when the normal game folder exists.

## Current published downloads

Release **v0.8.14** has two assets:

- `DpsMeter-0.8.14-win-x64.exe` — self-contained Windows EXE. Users do not need Python or .NET.
- `DpsMeter-0.8.14.py` — readable, dependency-free Python/Tkinter version.

Both should provide the same meter logic and features. Do not publish a change to only one version unless the release notes clearly call that out.

The EXE is built from the WPF/.NET project. The Python script is an independent implementation; it is not generated from the WPF code.

## Important locations

### GitHub source checkout

```text
C:\Users\shittboxx\Documents\Codex\2026-08-07\https-builds-soulbound-tools\work\github-soulbound-dps
```

Tracked GitHub files currently include:

- `DpsMeter.py`
- `README.md`
- `PROJECT_HANDOFF.md` (this document)
- `.gitignore`

### Windows EXE source project

```text
C:\Users\shittboxx\Documents\Codex\2026-08-07\https-builds-soulbound-tools\work\SoulboundMeter
```

Main EXE project files:

- `SoulboundMeter.csproj`
- `MainWindow.xaml`
- `MainWindow.xaml.cs`
- `Services\JsonLinesCombatLogSource.cs`
- `Services\AppSettings.cs`
- `Core\CombatSession.cs`
- `Core\FlexRecordStore.cs`
- `Assets\Abilities\` — bundled ability icons
- `Assets\Brand\DpsMeter.ico` — application icon
- `Assets\Brand\DpsMeterLoop.gif` — header animation

### Standard Soulbound combat-log folder

```text
%LOCALAPPDATA%\worldwidewebb\combat_logs
```

For the current Windows user this is normally:

```text
C:\Users\shittboxx\AppData\Local\worldwidewebb\combat_logs
```

### User-created local data

- `records.txt` is created beside the EXE or `DpsMeter.py`. It stores permanent Flex records and must never be removed by log cleanup.
- `settings.json` is stored at `%LOCALAPPDATA%\SoulboundMeter\settings.json`.
- Combat logs remain in the game folder unless the optional cleanup setting is enabled.

## Combat-log behavior and decisions

Each dungeon creates a separate log file. The meter must automatically select the newest **verified** Soulbound combat log in the selected folder. It should not force a user to choose one log file manually.

### Safety and reset behavior

- Only files with a valid Soulbound combat-log header count as game logs.
- The watcher pins the active log while it is being written.
- Logs can be rewritten/truncated in place. The meter must preserve visible totals and avoid the annoying behavior where totals disappear and then build back up.
- A `RUN_START` event inside the same active log must not clear visible totals mid-run.
- When a genuinely new dungeon log becomes active, begin a new current-run session while keeping permanent Flex records.

### Damage accounting

- The default live meter uses `applied_amount`: actual damage applied after the target health cap. This matches Gearforge by default and makes shared DPS screenshots comparable.
- The Settings tab includes **Include overkill damage**. When enabled, live totals use the uncapped post-target-mitigation amount instead.
- Flex personal-best hit records retain the full hit amount so a high hit is not capped merely because the target was nearly dead.
- **Damage · Last 30s** is the rolling total of all damage in the last 30 seconds.
- The smaller `DPS` number is that total divided by the 30-second time window. It is intentionally different from the rolling total.

### Event details currently handled

- Damage, healing, and shielding are tracked separately.
- `Fortify` is shown as the shielding ability; shield gained should appear under Shielding, not Healing.
- `Healing Pulse` is resolved when logs identify it indirectly/unknown.
- Unresolved `Unknown Ability` rows are hidden from the ability list while their valid amount remains in overall totals.
- Ability rows show: bundled icon, ability name, damage type (for example `VOID`), contribution bar, and amount.
- Hovering an ability shows its Normal/Crit/Heavy/Devastating hit breakdown.

### Hit classification

- Normal: neither crit nor heavy.
- Crit: crit only.
- Heavy: heavy only.
- Devastating: crit + heavy.

The header shows live current-run **Crit Chance**, **Heavy Chance**, and **Dev Chance**. Example: 10 damage hits with 2 heavy hits means 20% Heavy Chance.

The Flex tab tracks highest Normal, Crit, Heavy, and Devastating single hit, plus the other permanent records. The current meter also shows the current run highs for Crit, Heavy, and Devastating.

## Current UI/features

### Main meter

- Borderless, always-on-top overlay.
- Flex tab for permanent show-off records.
- Settings tab for theme color, opacity, AFK fade, AFK fade delay, font scale, follow-game-window, combat-log cleanup, and overkill handling.
- Compact / Normal layout toggle. Each layout remembers its own size.
- Resizing and font scale are persisted.
- Minimize must restore safely. The Python version temporarily restores normal Windows chrome before minimizing, then recreates the borderless always-on-top overlay when restored.
- Follow game window positions the overlay near Soulbound. It does not attach to or alter the game process.
- `Alt+Shift+D` toggles click-through lock.
- “Made by TundraWooK” is neon green in the lower right.

### Branding added in v0.8.14

- The supplied green/black Soulbound-style emblem is the EXE application icon.
- The EXE and Python window/taskbar use the green emblem.
- The animated version replaces the old upper-left `DPS METER`, PID, and `Reading ...` status block.
- The header now shows only the animated emblem and current map name. The map name is parsed from a log name such as `dungeon__Virelda_Outskirts__1__...log` and displayed as `Virelda Outskirts`.
- In Compact mode the emblem is smaller but still visible; the map remains on its own line.
- The Python branding is embedded as Base64 directly in `DpsMeter.py`, so it still distributes as one file.
- The WPF EXE branding is embedded as project resources.

Windows normally controls the Explorer icon for a `.py` file through the system Python file association. The Python script itself cannot reliably change that Explorer icon. Once launched, its window/taskbar uses the DPS Meter emblem.

## Asset sources and generated assets

Original emblem selected for the app:

```text
C:\Users\shittboxx\Downloads\ChatGPT Image Sep 2, 2026, 12_29_43 AM.png
```

Original animation assets:

```text
C:\Users\shittboxx\Documents\Codex\2026-09-02\i-n\outputs\
```

Source animation files observed there:

- `dps-emblem-loop-preview.gif` (60 frames)
- `dps-emblem-loop.webp` (60 frames)
- `dps-emblem-spritesheet-10x6.png`

Working generated previews/assets were placed under:

```text
C:\Users\shittboxx\Documents\Codex\2026-08-07\https-builds-soulbound-tools\work\branding-preview\
```

Do not hand-edit the enormous Base64 image constants in `DpsMeter.py`. If branding changes, regenerate the icon/sheet and then replace those generated constants deliberately.

## Building and testing

### Python

From the GitHub checkout:

```powershell
python -m py_compile DpsMeter.py
python DpsMeter.py --self-test
python DpsMeter.py --version
```

The self-test verifies parser behavior, live-vs-overkill amounts, unknown ability handling, Flex persistence, active-log rewrite protection, map parsing, and more. It should print `PASS`.

Python requirement for users: Python 3.10+ with Tkinter. There are no third-party Python package requirements.

### EXE

From the WPF project directory:

```powershell
dotnet build SoulboundMeter.csproj -c Release
dotnet publish SoulboundMeter.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o publish\0.8.XX
```

The `.csproj` must preserve these distribution settings:

- `TargetFramework`: `net8.0-windows`
- `RuntimeIdentifier`: `win-x64`
- `SelfContained`: `true`
- `PublishSingleFile`: `true`
- `IncludeNativeLibrariesForSelfExtract`: `true`
- `EnableCompressionInSingleFile`: `true`
- `ApplicationIcon`: `Assets\Brand\DpsMeter.ico`

The EXE can be validated with:

```powershell
$exe = Resolve-Path 'publish\0.8.XX\DpsMeter.exe'
[Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
```

## Release checklist

1. Keep the Python and WPF version numbers aligned (Python suffix such as `-py.1` is fine).
2. Run the Python self-test and build the WPF project without errors.
3. Test a real current combat log: damage, healing, Fortify shielding, ability resolution, current map, 30-second total, and hover tooltip.
4. Test Normal and Compact layouts, resize persistence, font scaling, settings, minimize/restore, AFK fading, and follow-game-window.
5. Copy the built EXE and `DpsMeter.py` to a clean release folder using versioned names:

   ```text
   DpsMeter-0.8.XX-win-x64.exe
   DpsMeter-0.8.XX.py
   ```

6. Update `README.md` when user-visible behavior changes.
7. Commit and push the Python source/documentation to `main`.
8. Create a GitHub release with both assets and clear notes. GitHub CLI is already authenticated for `TundraWookie` on this machine.

Example:

```powershell
gh release create v0.8.XX `
  'C:\path\DpsMeter-0.8.XX-win-x64.exe' `
  'C:\path\DpsMeter-0.8.XX.py' `
  --repo TundraWookie/SoulBound-Online-DPS-Meter `
  --target main `
  --title 'DPS Meter 0.8.XX' `
  --notes 'Release notes here'
```

9. Confirm the release contains exactly the expected EXE and Python assets.
10. Provide SHA-256 hashes if users need a way to verify downloads.

### v0.8.14 verification hashes

```text
DpsMeter-0.8.14-win-x64.exe
0DC6DB4F9F1672402BA725AD26F70531D9F7EB07C7D8B09CE6D65E8A72E4D7AD

DpsMeter-0.8.14.py
34F131BF64892DFBBA842E2523EB657D2912177052176248DE4BEF74BAB977B7
```

## GitHub history notes

- The accidental tracked `test` file and its old unprofessional message were removed in commit `0ac1c5d`.
- Compact mode, remembered size, and font scaling were restored in v0.8.13.
- Branding/current-map work was pushed in commit `201675a` and released as v0.8.14.
- Do not delete prior releases merely because they are old. The Code-page file list and the Releases page are separate; old release assets are useful unless the maintainer explicitly wants them removed.

## Things to watch / future testing

- Compare full-run totals against Gearforge with **Include overkill damage off**. This is the intended universal/default comparison mode.
- If the game combat-log schema changes, first save a fresh sample log and update parsing only from fields actually present in that log.
- Confirm every ability listed in the game wiki has a bundled icon and correct display name. The user specifically requested no generic fallback icons for known abilities.
- If a new unidentified event appears, do not guess its label. Inspect the most recent real log and determine its event type, source, amount field, and ability field first.
- Test map parsing against any log names that do not use the current `dungeon__Map_Name__...` pattern. The meter should fall back gracefully to the filename.
- Keep `records.txt` permanently safe. It is meant to be portable and visible beside the program so users can retain/show off records across updates.

## Common user support answers

- **“Do I need all the files from the build folder?”** No. Release the single self-contained EXE, or the single Python script.
- **“Where is records.txt?”** Next to the EXE or Python script after the program first creates records.
- **“Why is the EXE flagged/warned by Windows?”** It is a community-built unsigned app. Users should download only from the official GitHub Releases page or use the readable Python script.
- **“What does Follow game window do?”** It repositions the overlay near the Soulbound window; it does not hook into or modify the game.
- **“Why does the Python file show the Python icon in Explorer?”** Windows file association controls that. The running app itself has the custom DPS Meter icon.
- **“Why is the 30-second number larger than DPS?”** The large number is damage dealt over the last 30 seconds; DPS is that amount divided by time.


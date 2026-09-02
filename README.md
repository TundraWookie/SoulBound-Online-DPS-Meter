# Soulbound DPS Meter

A lightweight combat meter and overlay for **Soulbound Online**. It reads the combat logs produced by the game and displays your damage, healing, shielding, hit chances, ability totals, and permanent personal records while you play.

Created by **TundraWooK** with permission from Soulbound creator Tom Landon and the development team. This is a community project, not an official Soulbound release.

## Features

- Automatically finds Soulbound and the default combat-log folder.
- Automatically switches to the newest verified dungeon log.
- Shows the current map beneath an animated DPS Meter emblem.
- Handles in-place combat-log rewrites without resetting or replaying the visible totals.
- Tracks damage dealt, healing done, and shielding gained.
- Shows damage and healing during the last 30 seconds, plus DPS and HPS.
- Tracks critical, heavy, and devastating hit chances for the current run.
- Tracks the highest critical, heavy, and devastating hits during the current run.
- Shows ability names, bundled ability icons, damage types, contribution bars, and totals.
- Splits each ability bar into Normal, Crit, Heavy, and Devastating damage colors.
- Shows per-ability hit counts, damage, percentages, and averages when you hover over an ability.
- Resolves Healing Pulse and Fortify events when the log reports them as unknown.
- Hides unresolved `Unknown Ability` rows while retaining their amounts in the totals.
- Includes a permanent **Flex** tab for personal records and lifetime statistics.
- Supports custom menu colors.
- Supports adjustable overlay opacity and optional AFK fading between dungeon runs.
- Supports adjustable font size and remembers the resized window dimensions.
- Includes a compact horizontal layout with its own remembered window size.
- Uses embedded branding and application icons in both downloads; no extra asset files are required.
- Excludes overkill from live damage by default so totals match Gearforge, with an option to include it.
- Can follow the Soulbound game window.
- Optional combat-log cleanup keeps the newest 10 verified logs.
- Creates and updates `records.txt` live beside the program.

## Download

Download the latest version from the repository's **Releases** page.

Two versions are available:

- **Windows EXE:** A self-contained, single-file build. Python and the .NET runtime are not required.
- **Python script:** Readable source for users who prefer to inspect and run the program themselves. Requires Python 3.10 or newer with Tkinter.

Do not download or run files posted by third parties. Official project releases should come from this repository.

## Quick Start

### Windows EXE

1. Download the latest `DpsMeter-*-win-x64.exe` release.
2. Put it in its own folder.
3. Run the EXE.
4. Start Soulbound and enter a dungeon.
5. The meter should automatically find Soulbound's newest combat log.

### Python Version

1. Install Python 3.10 or newer with Tkinter.
2. Download `DpsMeter.py`.
3. Put it in its own folder.
4. Open PowerShell or Command Prompt in that folder and run:

```powershell
python DpsMeter.py
```

## Automatic Log Detection

The meter checks the following default folder first:

```text
%LOCALAPPDATA%\worldwidewebb\combat_logs
```

Each dungeon creates a separate combat log. The meter watches the folder and automatically begins reading the newest verified Soulbound log.

Files are only treated as combat logs when they contain a valid Soulbound combat-log header. Combat statistics come from the log files, not from reading game memory.

## Understanding the Meter

### Damage and Healing

- **Damage · Last 30s** is the total damage dealt during the rolling 30-second window.
- The smaller **DPS** number is that rolling total divided by 30 seconds.
- **Damage** is your total damage for the current dungeon log.
- **Healing · Last 30s** and **HPS** work the same way for healing.
- **Healing** and **Shielding** are tracked separately.

By default, live damage uses the game's `applied_amount`, excluding damage beyond the target's remaining health. This matches Gearforge's damage totals. Enable **Include overkill damage** in Settings to use the full post-mitigation hit instead. Flex records always retain full hit values so personal-best hits are not capped by a nearly defeated target.

### Hit Chances

Hit chances are calculated from your damage events in the current run:

```text
chance = matching hits / all damage hits × 100
```

- **Crit Chance:** Hits marked critical.
- **Heavy Chance:** Hits marked heavy.
- **Dev Chance:** Hits marked both critical and heavy.
- **Devastating:** A critical hit and heavy hit occurring together.

For example, if 2 of your 10 damage hits are heavy, the displayed Heavy Chance is 20%.

### Combat Time

When the combat log provides encounter start and end events, the timer counts active combat time. It pauses between encounters, including upgrade periods, and resumes when the next encounter begins.

### Top Abilities

The ability list shows the combined amount attributed to each ability during the current run. Damage, healing, and shielding abilities can appear in this list. Unresolved `Unknown Ability` entries are hidden from the list but remain included in the appropriate overall total.

Ability damage bars are split by hit type: white for Normal, red for Crit, orange for Heavy, and purple for Devastating. Hover over an ability to see each category's hit count, total damage, share of that ability's damage, and average hit. Healing and shielding amounts remain visible but are identified separately instead of being counted as damage hits.

## Flex Records

The **Flex** tab stores permanent personal records, including:

- Biggest single damage hit.
- Biggest single heal.
- Best damage within 60 seconds.
- Best healing within 60 seconds.
- Best total damage in one run.
- Best total healing in one run.
- Highest normal, critical, heavy, and devastating hits.
- Lifetime damage and healing.
- Number of runs recorded.

Records are saved live in:

```text
records.txt
```

The file is created beside the EXE or Python script. It is never removed by the combat-log cleanup option. Keep this file when updating the meter if you want to preserve your records.

Do not include your personal `records.txt` when sharing the meter with somebody else unless you intentionally want to share your records.

## Controls

- **Flex / Meter:** Switch between the live meter and permanent records.
- **Compact / Normal:** Switch between the full vertical meter and compact horizontal layout.
- **Settings button:** Change the menu color, opacity, font size, AFK fading, overkill handling, and log-cleanup preference.
- **Follow game window:** Keep the overlay positioned relative to Soulbound.
- **Alt+Shift+D:** Toggle click-through mode so mouse clicks pass through the overlay.

When **Fade when AFK / outside a dungeon** is enabled, the overlay gradually fades to 8% opacity after a dungeon run ends. The **Fade time** slider selects how long that transition takes, from 1 to 60 seconds. A new dungeon or encounter—or any detected player damage, healing, or shielding—quickly restores the selected normal opacity. Opening Settings also restores normal opacity so the controls remain easy to use.

## Settings and Local Files

The meter stores its appearance and window preferences here:

```text
%LOCALAPPDATA%\SoulboundMeter\settings.json
```

The saved preferences include the window position, resized width and height, font size, theme color, and overlay options.

Permanent records are stored beside the program in `records.txt`.

The optional cleanup setting:

- Is disabled by default.
- Only considers files with a verified Soulbound combat-log header.
- Keeps the newest 10 verified combat logs.
- Never deletes `records.txt`.

## Privacy and Safety

- The meter makes no network connections.
- It does not inject code into Soulbound.
- It does not read or modify Soulbound's memory.
- It only reads the selected combat-log folder and writes its own settings and records files.
- Ability icons are bundled locally with the application.

The Python release is provided as a single readable script for users who want to inspect exactly what the program does before running it.

## Troubleshooting

### Waiting for a combat log

- Start Soulbound and enter a dungeon so the game creates a log.
- Confirm the log folder exists at `%LOCALAPPDATA%\worldwidewebb\combat_logs`.
- Make sure the newest file is a real Soulbound combat log with a valid header.

### Soulbound is not running

The meter cannot currently find the Soulbound game window. Start the game and allow automatic attachment to retry. Log tracking can still work without window attachment; attachment is primarily used for window following.

### A skill is missing or named incorrectly

The meter can only display information present in the combat log. Open an issue and attach a short relevant log sample. Remove anything you do not want to share before uploading it.

### Damage looks lower than expected

Check whether you are comparing the large **Damage · Last 30s** total with the smaller **DPS** number underneath it. DPS is a per-second average; the large number is the complete rolling 30-second amount.

### Python reports that Tkinter is missing

Install the standard Windows build of Python and include the Tcl/Tk component. You can test the installation with:

```powershell
python -m tkinter
```

### Windows warns about the EXE

Community builds may be unsigned. Confirm that the file came from this repository's Releases page. If you do not want to run the EXE, use the readable Python version instead.

## Current Limitations

- Windows only.
- Tracks the local player's events, not a complete party meter.
- Depends on the combat-log fields and schema produced by Soulbound.
- New abilities or combat-log schema changes may require a meter update.
- Ability attribution is limited when the game itself reports an event without an ability name.

## Reporting Bugs or Requesting Features

Open a GitHub issue and include:

- Whether you used the EXE or Python version.
- The meter version.
- What you expected to happen.
- What actually happened.
- A screenshot, if relevant.
- A short combat-log sample when the issue involves parsing or an ability.

Please do not upload an entire log if a smaller sample demonstrates the problem.

## Running From Source

The Python edition has no third-party package requirements:

```powershell
python DpsMeter.py
```

Run its included self-test with:

```powershell
python DpsMeter.py --self-test
```

## Credits

- Created by **TundraWooK**.
- Soulbound Online created by Tom Landon and the Soulbound development team.
- Combat-log support provided by the Soulbound development team.
- Ability names and imagery belong to Soulbound and their respective rights holders.

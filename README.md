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
- Shows per-ability kill counts in the meter plus boss-encounter damage, hit counts, damage, percentages, and averages on hover.
- Resolves Healing Pulse and Fortify events when the log reports them as unknown.
- Hides unresolved `Unknown Ability` rows while retaining their amounts in the totals.
- Excludes unresolved abilities from ability-attributed Flex records so an unidentified hit or heal is never presented as a personal best.
- Includes a permanent **Flex** tab for personal records and lifetime statistics.
- Tracks dungeon runs by dungeon and difficulty, including extracted and abandoned runs.
- Imports existing combat logs once and keeps a permanent duplicate-prevention ledger in `records.txt`.
- Shows a room timeline below the ability list with readable combat-only checkpoint times in both normal and compact layouts.
- Includes a community **Ranks** tab for fastest completed runs, damage, DPS, healing, shielding, and other categories.
- Shows one leading score per dungeon and difficulty with your personal best beside it; hover a dungeon name for that category's color-coded top five.
- Excludes abandoned, failed, incomplete, and edited live runs from leaderboard rankings.
- Checks GitHub Releases on startup and asks before downloading and installing a newer version.
- Supports custom menu colors.
- Supports adjustable overlay opacity and optional AFK fading between dungeon runs.
- Supports adjustable font size and remembers the resized window dimensions.
- Includes a compact horizontal layout with its own remembered window size.
- Keeps a normal Windows taskbar button while open, minimized, and restored.
- Uses embedded branding and application icons in both downloads; no extra asset files are required.
- Excludes overkill from live damage by default so totals match Gearforge, with an option to include it.
- Can follow the Soulbound game window.
- Optional combat-log cleanup keeps the newest 10 verified logs.
- Creates and updates `records.txt` live beside the program.

## Download

Download from the files on this front page or use the repository's **Releases** page for versioned downloads:

- [Download the Windows EXE](DpsMeter.exe)
- [Download the readable Python version](DpsMeter.py)
- [Open versioned releases](https://github.com/TundraWookie/SoulBound-Online-DPS-Meter/releases/latest)

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

Enable **Damage effects** in Settings for live special-hit feedback. The affected ability's bar, name, and amount briefly flash red for a critical hit, orange for a heavy hit, or purple for a devastating hit, then return to the normal damage-breakdown colors.

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

The meter's **Run Time** clock uses Soulbound's full run clock—the same value submitted for fastest-time rankings. Relic selection, room transitions, and other pauses therefore remain visible in the displayed time. Combat-only duration is still tracked internally for performance statistics.

The room timeline below the ability list uses the same full run clock, so its final checkpoint matches the leaderboard time.

### Top Abilities

The ability list shows the combined amount attributed to each ability during the current run. Damage, healing, and shielding abilities can appear in this list. Unresolved `Unknown Ability` entries are hidden from the list but remain included in the appropriate overall total.

Ability damage bars are split by hit type: white for Normal, red for Crit, orange for Heavy, and purple for Devastating. Hover over an ability to see each category's hit count, total damage, share of that ability's damage, and average hit. Healing and shielding amounts remain visible but are identified separately instead of being counted as damage hits.

Ability kills are counted only when Soulbound marks the local player's outgoing damage as lethal against a monster. Soulbound sometimes anonymizes dungeon targets as `unknown`; those lethal hits are counted, while explicit player/self targets, party members' kills, and nonlethal overkill damage are not credited.

Each ability popup also separates damage dealt during Soulbound encounters marked `miniboss` or `bossraid`. This is labeled **Boss encounter damage** because boss encounters can include additional enemies and the log does not give every target a definitive boss flag.

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
- Dungeon history grouped by dungeon and difficulty. Hover over the summary for color-coded completed, abandoned, and ended-early counts plus the fastest completed wall-clock time. New dungeons automatically receive their own persistent color.

Records are saved live in:

```text
records.txt
```

The file is created beside the EXE or Python script. On the first launch of a version with dungeon history, the meter scans the existing combat-log folder and imports every run once. Its permanent ledger prevents those logs from being counted again on later launches or rescans. After a log has been imported, deleting the original combat log does not remove its saved dungeon history.

It is never removed by the combat-log cleanup option. Keep this file when updating the meter if you want to preserve your records and duplicate-prevention ledger.

Do not include your personal `records.txt` when sharing the meter with somebody else unless you intentionally want to share your records.

## Community Leaderboard

Open **Ranks**, choose a permanent display name, and select **Join** to submit qualifying runs. On first use, **Scan history** can import completed extractions from existing combat logs so older legitimate runs are not lost.

- Rankings and player names are visible only after joining with a registered player name.
- Only completed extractions are eligible. Abandoned, failed, ended-early, and incomplete runs are excluded.
- Boss raids such as Spectra Lair require a verified `bossraid` encounter lifecycle. A live encounter start is accepted normally; a snapshot start is accepted only when that log also records Spectra's lethal hit before the completion event. This keeps partial or ambiguous encounter endings out without treating every state snapshot as a late join. A party record must also be submitted by a member who remained alive through the ending, because a dead client receives the same ambiguous encounter-end event after either a clear or a wipe.
- Party size is checked against unique player identities observed in the completed log. Under-reported counts are corrected, missing party data is never assumed to mean Solo, and legitimate Spectra Solo clears remain visible.
- Hover a party-size number in a ranking's Top 5 popup to see the unique party names that the selected combat log actually exposed. Incomplete rosters are labeled instead of guessed.
- When a ranking contains a complete party roster, its player label rotates through every member so the record visibly credits the whole party; Solo and incomplete-roster entries keep the submitting player's name.
- Fastest-time Top 5 rankings count each distinct party roster once, so several members uploading the same clear cannot occupy multiple places. Damage, healing, and other personal categories remain player-based.
- Spectra Normal and Hard are identified only from their invariant incoming `raw_amount` attack signatures (50/80/150 for Normal and 75/240/250 for Hard), so party clears are separated correctly despite mitigation. Damage dealt to Spectra remains an informational statistic and never determines mode or leaderboard eligibility.
- During a Spectra fight, the live current-map label adds `Normal` or `Hard` as soon as one of those incoming-damage signatures is observed.
- Empty late-join logs with no recorded damage, healing, or shielding cannot own a fastest-time record.
- Automatic history migrations preserve previously scanned non-Spectra files and throttle any required archive parsing so the live meter and timer stay responsive.
- Completed runs are read from their recorded combat logs and added automatically after the run ends.
- Leaderboard submissions send the run summary and a SHA-256 source-file fingerprint, not the combat-log contents.
- Each player can occupy only one top-five position per dungeon and difficulty, using their best qualifying score for the selected category and filters.
- Leaderboard results refresh every 2 minutes while the Ranks tab is open, immediately after your completed run is accepted, or whenever **Refresh** is selected.
- Dungeon catalog results are cached for six hours, and each unchanged combat log is processed only once to keep community Cloudflare usage within the free allowance.
- The leaderboard groups difficulty sections hardest to easiest: Raid, Abyssal, Shattered, Collapsing, Fractured, Unstable, then Stable. The difficulty filter remains ordered easiest to hardest.

## Controls

- **Flex / Meter:** Switch between the live meter and permanent records.
- **Ranks:** Browse community records and manage your leaderboard name/history scan.
- **Compact / Normal:** Switch between the full vertical meter and compact horizontal layout.
- **Settings button:** Change the menu color, opacity, font size, AFK fading, overkill handling, Soulbound mob-health display, and log-cleanup preference.
- **Follow game window:** Keep the overlay positioned relative to Soulbound.
- **Alt+Shift+D:** Toggle click-through mode so mouse clicks pass through the overlay.

When **Fade when AFK / outside a dungeon** is enabled, the overlay gradually fades to 8% opacity after a dungeon run ends. The **Fade time** slider selects how long that transition takes, from 1 to 60 seconds. A new dungeon or encounter—or any detected player damage, healing, or shielding—quickly restores the selected normal opacity. Opening Settings also restores normal opacity so the controls remain easy to use.

The **Soulbound → Mob health numbers** control reads `%LOCALAPPDATA%\worldwidewebb\settings.dat` each time Settings opens and shows whether the game's `debug_show_mob_health` flag is currently on or off. The same button toggles it in either direction. Fully close and relaunch Soulbound after changing it.

## Settings and Local Files

The meter stores its appearance and window preferences here:

```text
%LOCALAPPDATA%\SoulboundMeter\settings.json
```

The saved preferences include the window position, resized width and height, font size, theme color, and overlay options.

### Automatic Updates

Automatic update checks are enabled by default and can be disabled under **Settings → Updates**. When a newer GitHub Release is available, the meter displays a Yes/No prompt. It downloads nothing until you approve.

After approval, the meter downloads the matching EXE or Python asset beside the currently running file, verifies its GitHub-published size and SHA-256 digest, closes the old copy, atomically replaces it, and opens the new copy. A failed or altered download never replaces the installed version.

Permanent records are stored beside the program in `records.txt`.

The optional cleanup setting:

- Is disabled by default.
- Only considers files with a verified Soulbound combat-log header.
- Keeps the newest 10 verified combat logs.
- Never deletes `records.txt`.

## Privacy and Safety

- The meter contacts GitHub to check for updates. Downloads only begin after approval.
- It contacts the community leaderboard service to retrieve member-only rankings. Viewing names or scores and submitting runs requires joining with a display name; submissions can be disabled in Settings.
- Every registered member can hover over **Player list** to see the registered display-name roster and which names currently have at least one qualifying score. This summary does not include authentication tokens or combat-log contents.
- Leaderboard submissions contain run statistics, timing metadata, and cryptographic log fingerprints—not the combat-log contents.
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

### Leaderboard connection fails

The meter writes privacy-safe connection diagnostics to `leaderboard-errors.log` beside the program. If that folder is not writable, the log is stored at `%LOCALAPPDATA%\SoulboundMeter\leaderboard-errors.log`. Attach that file when reporting the problem; authentication tokens and submitted run data are not recorded.

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

To create the Windows EXE with its embedded file icon, install PyInstaller and run:

```powershell
.\build_windows.ps1
```

## Credits

- Created by **TundraWooK**.
- Soulbound Online created by Tom Landon and the Soulbound development team.
- Combat-log support provided by the Soulbound development team.
- Ability names and imagery belong to Soulbound and their respective rights holders.

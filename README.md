<p align="center">
  <img src="icons/icon.png" alt="OK-Endfield logo" width="256" height="256" />
</p>

# OK-Endfield — Global Language Fixes

An unofficial fork of [AliceJump/ok-end-field](https://github.com/AliceJump/ok-end-field) focused on making OK-Endfield work with the English interface of the global version of **Arknights: Endfield**. The tool automates parts of the game through screen recognition and simulated Windows inputs. Background support is partial, and keyboard-controlled actions may need the game window to be active.

[![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue)](#requirements)
[![Upstream release](https://img.shields.io/github/v/release/AliceJump/ok-end-field)](https://github.com/AliceJump/ok-end-field/releases)
[![Upstream downloads](https://img.shields.io/github/downloads/AliceJump/ok-end-field/total)](https://github.com/AliceJump/ok-end-field/releases)
[![Upstream Discord](https://img.shields.io/discord/296598043787132928?color=5865f2&label=Discord)](https://discord.gg/vVyCatEBgA)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/AliceJump/ok-end-field)

## What this fork changes

- Enables the English OCR matchers. The Wuling City farming route recognizes **Index → Energy Alluvium** even when the English category label wraps onto two lines.
- Makes auto-combat release the attack button when an end-of-combat signal appears and wait for confirmation before exiting.
- Adds **Daily Tasks → Battle → Burst delay (seconds)**. Basic attacks and target search can start immediately, while the skill rotation waits for the chosen delay. The default is zero.

English coverage varies by task. The OCR and combat changes were checked on saved frames or in simulations. The complete Wuling harvest still needs an in-game check.

## Quick start

The fork's changes are available in its source code. Follow [Run from source](#run-from-source) below to use them.

For the original version, download the Global Windows installer from [upstream GitHub Releases](https://github.com/AliceJump/ok-end-field/releases), run the setup wizard, and launch **ok-ef** from the Start menu or desktop shortcut. Look for a `setup.exe` release asset. GitHub's automatically generated source archives do not contain a Windows installer.

### Upstream download sources

- [GitHub Releases](https://github.com/AliceJump/ok-end-field/releases)
- [MirrorChyan](https://mirrorchyan.com/zh/projects?rid=ok-end-field&source=ok-ef-readme), a regional mirror that may require a platform key
- [Baidu Netdisk and Quark Netdisk](https://github.com/AliceJump/ok-end-field#-%E4%B8%8B%E8%BD%BD%E6%B8%A0%E9%81%93), free mirrors listed by the upstream project

[Upstream download statistics](./.github/stats/downloads.svg) · [Documentation](https://ok-script.com/ok-end-field/) · [Demo and tutorial on Bilibili](https://www.bilibili.com/video/BV16PPszhEwN/) · [English tutorial on YouTube](https://youtu.be/h6P1KWjdnB4)

## Disclaimer

This is an external tool for automating repetitive steps in Arknights: Endfield. The features described here use on-screen recognition and ordinary Windows input. The project is open source and free, and its upstream README describes it as intended for personal learning and exchange. See the [license](LICENSE) for the applicable terms.

The game's fair-play notice warns that using unauthorized third-party tools such as bots, macros, and cheats can lead to forfeiture of rewards, suspension, or a permanent ban. Use the tool at your own risk and check the game's current rules. The game name and trademarks belong to their respective owners.

## Requirements

- Windows with a 16:9 game resolution of at least **1600 × 900**.
- A stable **60 FPS** is recommended for combat and navigation.
- Use a simple installation path such as `D:\Games\ok-ef`. Avoid paths with non-ASCII characters and protected folders such as `C:\Program Files`.
- The upstream project recommends running as administrator and requires elevation for its source workflow.
- Set the app and game to the same language. Some upstream tasks still rely on Simplified Chinese labels.

## Features

### One-time tasks

- [Daily Tasks](docs/en/daily-tasks.md) covers gifts, outpost exchanges, delivery requests, trading, Sanity farming, and reward collection.
- [Sanity Farming](docs/en/stamina-farming.md) supports standard and higher-tier stages, Crisis stages, and Energy Alluvium, with skill rotations and stage sequences.
- [Delivery Request Pickup](docs/en/delivery-pickup.md) filters requests by credit type and amount.
- [Auto Delivery](docs/en/auto-delivery.md) picks up and delivers Wuling requests worth 73,100, 79,800, 119,000, 159,000, or 163,000 credits.
- [Warehouse Transfer](docs/en/warehouse-transfer.md) moves selected items between warehouses in bulk.
- **Calculation card draws** repeat at the arena until the configured level-change condition is met.
- **Umbral Monument** automates currently available normal stages.
- **Launch Game Once** can be scheduled to start and check the game. The 120-second value is the timeout for reaching the main screen. By default the task exits 15 seconds after reaching it.
- **Real-time detection** runs YOLO continuously for diagnostics. Other development tools include periodic screenshots and framework diagnostics. The older endgame essence recognition task has been removed upstream.

### Trigger tasks

- [Auto-combat](docs/en/auto-combat.md) detects combat and runs skill sequences.
- **Auto Interaction** skips supported story dialogs and selects teleport actions on the map.
- **Auto Pickup** uses allowlists and denylists.
- [Item Navigation](docs/en/item-navigation.md) uses the shared `world.pose` position to point toward the nearest gathering location.

### Scheduled tasks

Daily Tasks, Auto Delivery, Umbral Monument, and Launch Game Once support the built-in scheduler. [Windows Task Scheduler](docs/en/windows-task-scheduler.md) can run any registered one-time task.

The framework also provides OCR, template matching, HSV color detection, input simulation, logging, error handling, and task scheduling.

## Troubleshooting

1. Use a simple installation path and confirm that the app can access the game window.
2. If antivirus software quarantines a file, verify that it came from a trusted release before deciding whether to allow it.
3. Use the game's default brightness. Turn off GPU filters, extra sharpening, and overlays such as MSI Afterburner or Fraps unless a guide for the feature calls for them.
4. Mirror any custom in-game keybindings in the tool's settings. Only listed hotkeys are supported.
5. Check that you are running the intended version. To use the changes described here, run this fork's source.
6. If the frame rate is unstable, lower the game's graphics settings while keeping the supported resolution.
7. If the game repeatedly disconnects, try starting it manually and letting it run for five minutes before launching the tool. After a disconnect, try signing back in before closing it.
8. When reporting a problem, include the task, game language, version, and steps to reproduce. Remove player identifiers and other account information from any logs or screenshots you choose to share.
9. Consult [upstream troubleshooting](docs/en/guides/troubleshooting.md) for task-specific setup and limitations.

## Maintenance documentation

The guides below are upstream documents and may be in Chinese.

| Guide | Contents |
| --- | --- |
| [Auto Delivery maintenance](docs/update/%E9%80%81%E8%B4%A7%E5%9C%B0%E5%8C%BA%E7%BB%B4%E6%8A%A4%E5%B7%A5%E4%BD%9C%E6%B5%81.md) | Delivery regions, templates, and validation |
| [Daily gifting maintenance](docs/update/%E6%97%A5%E5%B8%B8%E9%80%81%E7%A4%BC%E7%BB%B4%E6%8A%A4%E5%B7%A5%E4%BD%9C%E6%B5%81.md) | Operator data and interaction templates |
| [Master data maintenance](docs/update/%E4%B8%BB%E6%95%B0%E6%8D%AE%E7%BB%B4%E6%8A%A4%E5%B7%A5%E4%BD%9C%E6%B5%81.md) | World regions, stages, and item data |

## Development

| Guide | Contents |
| --- | --- |
| [Quick start](docs/dev/QUICKSTART.md) | Run from source and add trigger or one-time tasks |
| [Development guide](docs/dev/DEVELOPMENT.md) | Architecture, task registration, tests, and releases |
| [API reference](docs/dev/API.md) | `BaseEfTask`, mixins, screen positions, and key configuration |
| [Localization and OCR](docs/dev/i18n_OCR%E9%85%8D%E7%BD%AE%E6%B5%81%E7%A8%8B.md) | Runtime language, matcher data, and OCR corrections |
| [Keyboard input](docs/dev/%E9%94%AE%E7%9B%98%E6%93%8D%E4%BD%9C%E4%BD%93%E7%B3%BB.md) | Hotkey mapping and input conventions |

### Run from source

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). On Windows, run the following from an elevated PowerShell session.

```powershell
git clone --recurse-submodules https://github.com/angelika3377/ok-end-field-global.git
Set-Location ok-end-field-global
uv sync --locked
uv run --locked python main.py
```

If the checkout already exists, run `git submodule update --init --recursive` from its root. For debug mode, use `uv run --locked python main_debug.py`.

### Command-line arguments

```powershell
ok-ef.exe -t 1 -e
```

- `-t` or `--task` runs the specified one-time task at startup. Task 1 is Daily Tasks in the [task list](src/config.py).
- `-e` or `--exit` closes the app after the task finishes.

### Debugging and tests

```powershell
./scripts/testing/run_tests.ps1
uv run --locked python -m unittest tests.TestGameWindow
```

For OCR, template, and color-recognition issues, use `main_debug.py` and inspect the relevant local logs and screenshots.

## Upstream community

[Discord](https://discord.gg/vVyCatEBgA) · [QQ Channel](https://pd.qq.com/s/djmm6l44y) · [QQ user and developer groups](https://github.com/AliceJump/ok-end-field#-%E5%8A%A0%E5%85%A5%E6%88%91%E4%BB%AC)

The upstream developer group is intended for contributors with a GitHub account who can already run the project from source. The [ok-script](https://ok-script.com/) framework can also be used to build other automation projects.

## Other projects using ok-script

- [Arknights: Endfield](https://github.com/AliceJump/ok-end-field)
- [Wuthering Waves](https://github.com/ok-oldking/ok-wuthering-waves) and [its enhanced daily-task fork](https://github.com/zzc-tongji/ok-ww-enhanced)
- [Genshin Impact](https://github.com/ok-oldking/ok-genshin-impact), unmaintained upstream, with background story skipping
- [Girls' Frontline 2: Exilium](https://github.com/ok-oldking/ok-gf2)
- [Honkai: Star Rail](https://github.com/Shasnow/ok-starrailassistant)
- [Blue Protocol: Star Resonance](https://github.com/Sanheiii/ok-star-resonance)
- [Duet Night Abyss](https://github.com/BnanZ0/ok-duet-night-abyss)
- [Neverness to Everness](https://github.com/BnanZ0/ok-nte)
- [Chaos Zero Nightmare](https://github.com/baoxin1100/ok-kes)
- [Ash Echoes](https://github.com/ok-oldking/ok-baijing), unmaintained upstream

## Acknowledgements

Thanks to [AliceJump](https://github.com/AliceJump) and the [OK-Endfield contributors](https://github.com/AliceJump/ok-end-field/graphs/contributors) for the original project, and to [ok-oldking](https://github.com/ok-oldking) and the [ok-script](https://ok-script.com/) contributors for the framework.

The upstream project also credits [OnnxOCR](https://github.com/ok-oldking/OnnxOCR), [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets), and [AutoSplit](https://github.com/Toufool/AutoSplit). Upstream Windows binaries receive code-signing support from [SignPath.io](https://signpath.io/) with a certificate from the [SignPath Foundation](https://signpath.org/).

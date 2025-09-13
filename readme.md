# Reaction Video Maker Pro

Create polished **reaction videos (PiP)** for YouTube/Shorts/Reels with a sleek **Tkinter + ttkbootstrap** GUI. Drag to position the reaction window, pick shapes (circle/square/rounded/polygon), mix audios, **batch render** entire folders, and export with **CRF/preset/FPS** controls (CPU or **NVENC** when available).

<p align="center">
  <img alt="Reaction Video Maker Pro – screenshot placeholder" src="https://img.shields.io/badge/GUI-Tkinter%20%2B%20ttkbootstrap-blue" />
  <img alt="FFmpeg required" src="https://img.shields.io/badge/FFmpeg-required-important" />
  <img alt="License" src="https://img.shields.io/badge/license-choose--one-lightgrey" />
  <img alt="OS" src="https://img.shields.io/badge/OS-Windows%20%7C%20macOS%20%7C%20Linux-informational" />
</p>

> **Highlights**
>
> * 🎯 **Presets**: YouTube (16:9), Shorts/TikTok/Reels (9:16), IG Square (1:1)
> * 🖼️ **PiP layout**: drag, resize, keep aspect, position presets, safe area guides
> * 🔷 **Shapes**: Circle, Square, Rounded, Polygon + **stroke color/width**
> * 🎚️ **Export controls**: **CRF slider (0–28)**, **preset** (ultrafast→veryslow), **FPS** (Auto/24/30/60/120), codec (**libx264/libx265/NVENC**)
> * 🎧 **Audio**: Base only / Reaction only / **Mix** with balance slider
> * 📁 **Batch rendering**: queue a folder and go 🚀
> * 🖼️ **Snapshots**: export PNG of current composite

---

<details>
  <summary><b>What the demo shows</b> (click to expand)</summary>

* Loading **Base** (Video 1) and **Reaction** (Video 2)
* Dragging & resizing the PiP with **aspect lock**
* Switching **shape** to Circle/Polygon, tweaking **stroke**
* Enabling **Safe Area** and moving PiP to **Kanan‑Bawah** preset
* Setting **CRF 18**, **preset fast**, **FPS 60**, codec **h264\_nvenc**
* Mixing audio: **Base 60% / Reaction 40%**
* Single render → then **Batch render** for a folder

</details>

---

## Features

* **GUI-first workflow** with **live preview**
* **Project presets**: YouTube 16:9, Shorts/TikTok/Reels 9:16, IG 1:1
* **Resolution selector** tied to preset (e.g., 1080×1920 for 9:16)
* **PiP tools**: presets (corners/center), **scale %**, **rotation**, **opacity**, **aspect lock**
* **Shape masks**: Full, Square, Circle, Rounded (radius), Polygon (sides)
* **Stylish outlines**: stroke width & color picker
* **Audio mixer** with 3 modes (Base / Reaction / Mix + slider)
* **Batch queue** with per-file and total progress bars
* **Hardware-aware**: auto-detects **NVENC** and falls back to CPU if missing
* **Export knobs**: codec, audio codec/bitrate, **CRF**, **preset**, **FPS**

---

## Install

> Requires **Python 3.10+** and **FFmpeg** on PATH.

### 1) FFmpeg

* **Windows**: Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) → add `/bin` to **PATH**
* **macOS**: `brew install ffmpeg`
* **Linux**: `sudo apt install ffmpeg` (Debian/Ubuntu) or your distro package

### 2) Python deps

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -U pip
pip install ttkbootstrap pillow opencv-python moviepy numpy
```

---

## Quick Start

```bash
python reaction_video_maker_pro_v2.py
```

1. **Open Single Video 1** → pick your **Base** video
2. **Open Video 2 (Reaction)** → pick your reaction webcam/clip
3. Pick **Preset** (e.g., YouTube Shorts) and **Resolution**
4. In **PiP/Layout** tab: position, scale, and style the reaction window
5. In **Export** tab: choose **FPS**, **CRF**, **preset**, and **codec**
6. Click **🚀 Render Video** → choose output filename/folder

> **Batch mode**: Use **Batch** tab → **Add Folder** with Base videos → **🚀 Render Video** → choose output folder. The app loops Reaction video to match each Base.

---

## How It Works

<details>
  <summary><b>Composite pipeline (simplified)</b></summary>

* Read frames at current timeline position from **Base** & **Reaction**
* Resize Base for **Contain/Cover** fit to the target canvas
* Resize Reaction to PiP **width/height** based on **scale %**
* Generate a **mask** (Circle/Square/Rounded/Polygon) + optional **stroke**
* Blend PiP onto Base using the mask → display on canvas
* For export, generate frames via MoviePy callback at target **FPS**
* Compose audio according to mode (Base/Reaction/Mix w/ level)
* Write video via FFmpeg:

  * **CPU**: `libx264`/`libx265` with `-crf` + `-preset`
  * **NVENC**: `h264_nvenc`/`hevc_nvenc` with `-rc vbr -cq <CRF>`

</details>

---

## Shortcuts & Tips

| Action              | Key                           |
| ------------------- | ----------------------------- |
| Play / Pause        | `Space`                       |
| Seek ±1s            | `←` / `→`                     |
| Seek ±5s            | `Shift` + `←` / `Shift` + `→` |
| Jump to start / end | `Home` / `End`                |
| Save snapshot (PNG) | `S`                           |
| Start render        | `Ctrl` + `R`                  |

**Tooltips** in the Export tab explain **CRF**, **FPS**, and **Preset** trade‑offs.

---

## FAQ

**Q: What is CRF?**
**A:** Constant Rate Factor controls quality for x264/x265. **Lower = better quality (bigger file)**. Common range **18–23**. `0 = lossless`.

**Q: Which FPS should I pick?**
**A:** **Auto** uses source FPS. 24/30 are typical. **60** for fast motion. **120** is niche (high‑frame‑rate sources/displays).

**Q: Preset vs speed?**
**A:** **Slower preset = better compression** (smaller file) but longer encode time. `fast` is a good balance.

**Q: NVENC not found?**
**A:** The app checks FFmpeg codecs and **falls back** to CPU (`libx264`) if `h264_nvenc`/`hevc_nvenc` are missing.

---

## Troubleshooting

* **“FFmpeg not found”** → Install FFmpeg and ensure it’s on PATH; relaunch app.
* **No preview / black canvas** → Verify both videos open; try different formats; check console logs.
* **Audio out of sync** → Use **Auto FPS** (source FPS) or match Base FPS.
* **Very slow export** → Try **higher CRF** (e.g., 22) and **faster preset** (e.g., `fast`/`faster`).
* **NVENC errors** → Switch codec to `libx264`.

---

## Roadmap

* ✅ Export controls: **FPS/CRF/Preset** UI with tooltips
* ✅ **NVENC auto-detect** + CPU fallback
* ✅ **Batch rendering** with progress bars
* ⏳ Save/Load project (load)
* ⏳ Custom PiP **drop shadow** params
* ⏳ More shape effects (feather/blur)
* ⏳ Command‑line interface (CLI)

> Want something added? Open an **Issue** with “Feature Request” template.

---

## Contributing

Pull Requests welcome! If you’re adding UI or export features, please:

* Keep UX consistent with ttkbootstrap’s **darkly** theme
* Add short **tooltips** for new controls
* Update **README** screenshots/GIFs if the UI changes

---


## Acknowledgements

* [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap)
* [MoviePy](https://zulko.github.io/moviepy/)
* [OpenCV](https://opencv.org/)
* [Pillow](https://python-pillow.org/)

---

### Run command (copy‑paste)

```bash
python reaction_video_maker_pro_v2.py
```

> *Pro tip:* For Shorts/TikTok/Reels, pick **9:16 1080×1920**, **CRF 18–22**, **preset fast**, and `h264_nvenc` when available for quick exports.

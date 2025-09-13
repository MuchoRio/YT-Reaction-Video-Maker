# reaction_video_maker_pro_v2.py

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from PIL import Image, ImageTk, ImageDraw
import cv2
import numpy as np
import moviepy.editor as mp
from moviepy.audio.fx.all import audio_loop
import threading
import queue
import subprocess
import sys
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
import math
import time
from typing import Tuple, Optional, Dict, Any, List

# --- Konfigurasi Logging ---
log_format = '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)

# --- Internationalization (i18n) String Table ---
# (Tidak berubah)
STRINGS = {
    "en": {
        "app_title": "Reaction Video Maker Pro",
        "status_welcome": "Welcome! Open videos to start.",
        "status_rendering": "Rendering: {file}...",
        "status_render_eta": "Rendering: {file} ({progress}%) - ETA: {eta}",
        "status_render_done": "Success! Saved to: {file}",
        "status_render_error": "Error! Failed to render video.",
        "status_render_cancelled": "Render cancelled by user.",
        "status_batch_done": "Batch rendering complete! {count} videos processed.",
        "tooltip_pip_scale": "Scale the reaction video size (percentage of the shorter output dimension).",
        "tooltip_crf": "Angka lebih kecil = kualitas lebih tinggi (file lebih besar). 18–23 adalah sweet spot. 0 = lossless.",
        "tooltip_fps": "Auto mengambil FPS dari video sumber. 24/30 untuk umum, 60 untuk gerakan cepat, 120 untuk khusus.",
        "tooltip_preset": "Preset lebih lambat = kompresi lebih baik (file lebih kecil, encode lebih lama). 'fast' adalah pilihan seimbang.",
        "confirm_cancel_render": "Are you sure you want to cancel the current rendering job?",
        "ffmpeg_not_found_title": "FFmpeg Not Found",
        "ffmpeg_not_found_msg": "This application requires FFmpeg to render videos. Please install FFmpeg and ensure its location is in your system's PATH.\n\nDownload from: https://ffmpeg.org/download.html"
    },
}
LANG = "en"
def _(key, **kwargs):
    return STRINGS[LANG].get(key, key).format(**kwargs)

# --- Model Data (State Management) ---
# (dataclasses lainnya tidak berubah)
@dataclass
class SafeAreaState:
    enabled: bool = True
    margin_percent: int = 5

@dataclass
class TimelineState:
    current_frame: int = 0
    total_frames: int = 0
    duration_sec: float = 0.0
    is_playing: bool = False
    is_scrubbing: bool = False

@dataclass
class ProjectState:
    video1_paths: List[str] = field(default_factory=list)
    video2_path: str = ""
    output_preset: str = "YouTube Video (16:9)"
    output_resolution: str = "1920x1080"
    fit_mode: str = "Contain"
    safe_area: SafeAreaState = field(default_factory=SafeAreaState)
    processing_mode: str = "Single"
    output_dir: str = ""

@dataclass
class PipShadowState:
    enabled: bool = False
    offset_x: int = 5
    offset_y: int = 5
    blur_radius: int = 10
    color: str = "#000000"
    opacity: float = 50.0

@dataclass
class PipLayoutState:
    pos_preset: str = "Kanan-Bawah"
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    scale_percent: float = 25.0
    rotation: float = 0.0
    opacity: float = 100.0
    lock_aspect: bool = True
    shadow: PipShadowState = field(default_factory=PipShadowState)

@dataclass
class ShapeStyleState:
    shape: str = "Bulat (Circle)"
    corner_radius: int = 15
    polygon_sides: int = 5
    stroke_width: int = 4
    stroke_color: str = "#FFFFFF"

@dataclass
class AudioState:
    mode: str = "Mix"
    v1_mute: bool = False
    v2_mute: bool = False
    mix_level: float = 50.0
    
@dataclass
class ExportState:
    # --- Diperbarui dengan state baru ---
    target_fps: str = "Auto"
    crf: int = 20
    preset: str = "fast" # Default baru
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    video_codec: str = "libx264"

# --- Aplikasi Utama ---
class ReactionVideoMakerApp:
    def __init__(self, root: ttkb.Window):
        self.root = root
        self.root.title(_("app_title"))
        self.root.geometry("1600x950")
        self.style = ttkb.Style(theme='darkly')

        # --- State Management ---
        self.project = ProjectState()
        self.pip_layout = PipLayoutState()
        self.shape_style = ShapeStyleState()
        self.audio = AudioState()
        self.export = ExportState() # Menggunakan state yang sudah diperbarui
        self.timeline = TimelineState()
        self.state_is_dirty = True
        self._after_id_preview = None

        # --- Internal Variables ---
        self.v1_cap: Optional[cv2.VideoCapture] = None
        self.v2_cap: Optional[cv2.VideoCapture] = None
        self.v1_meta: Dict[str, Any] = {}
        self.v2_meta: Dict[str, Any] = {}
        self.preview_queue = queue.Queue(maxsize=2)
        self.ui_update_queue = queue.Queue()
        self.ffmpeg_path = self.find_ffmpeg()
        self.is_nvenc_available = self._check_nvenc_availability() # Deteksi GPU
        self.rendering_process: Optional[subprocess.Popen] = None
        self.cancel_render_event = threading.Event()
        self.mask_cache = {}

        # --- Drag & Resize PiP ---
        self.pip_interaction_mode = None
        self.active_handle = None
        self.drag_start_pos = (0, 0)
        self.original_pip_geom = (0, 0, 0, 0)
        self.aspect_ratio = 1.0
        self.photo = None

        # --- UI Setup ---
        self._create_widgets()
        self._bind_events()
        self.status_label.config(text=_("status_welcome"))

        # --- Start Background Threads ---
        self.preview_thread = threading.Thread(target=self._preview_playback_manager, daemon=True, name="PreviewPlayback")
        self.preview_thread.start()
        self.root.after(100, self._update_preview_canvas)
        self.root.after(100, self._process_ui_updates)

        if not self.ffmpeg_path:
            self._show_ffmpeg_warning()
            
    def _check_nvenc_availability(self) -> bool:
        if not self.ffmpeg_path:
            return False
        try:
            result = subprocess.run([self.ffmpeg_path, "-codecs"], capture_output=True, text=True, encoding='utf-8')
            return "h264_nvenc" in result.stdout and "hevc_nvenc" in result.stdout
        except Exception as e:
            logger.error(f"Gagal memeriksa ketersediaan NVENC: {e}")
            return False

    def _show_diagnostics(self):
        nvenc_status = "Tersedia" if self.is_nvenc_available else "Tidak Tersedia"
        messagebox.showinfo(
            "Diagnostics",
            f"FFmpeg Path: {self.ffmpeg_path or 'Tidak Ditemukan'}\n"
            f"NVIDIA NVENC: {nvenc_status}"
        )

    # ... (Metode inti lainnya seperti find_ffmpeg, queue_ui_update, dll. tidak berubah) ...
    def find_ffmpeg(self) -> Optional[str]:
        try:
            cmd = "where" if sys.platform == "win32" else "which"
            result = subprocess.run([cmd, "ffmpeg"], capture_output=True, text=True, check=True)
            path = result.stdout.strip()
            logger.info(f"FFmpeg ditemukan di: {path}")
            return path
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("FFmpeg tidak ditemukan di PATH sistem.")
            return None

    def _show_ffmpeg_warning(self):
        messagebox.showwarning(_("ffmpeg_not_found_title"), _("ffmpeg_not_found_msg"))

    def queue_ui_update(self, func, *args, **kwargs):
        self.ui_update_queue.put((func, args, kwargs))

    def _process_ui_updates(self):
        try:
            while not self.ui_update_queue.empty():
                func, args, kwargs = self.ui_update_queue.get_nowait()
                func(*args, **kwargs)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._process_ui_updates)
            
    def _create_top_toolbar(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=X, pady=(0, 5))
        ttk.Button(toolbar, text="📂 Open Single Video 1", command=self._open_single_video1, style="primary.TButton").pack(side=LEFT, padx=2)
        ttk.Button(toolbar, text="📂 Open Video 2 (Reaction)", command=self._open_video2, style="success.TButton").pack(side=LEFT, padx=(10, 2))
        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y, ipady=5)
        # ... (Preset & Resolusi tidak berubah)
        ttk.Label(toolbar, text="Preset:").pack(side=LEFT, padx=(5, 2))
        self.preset_var = tk.StringVar(value=self.project.output_preset)
        presets = ["YouTube Video (16:9)", "YouTube Shorts (9:16)", "TikTok (9:16)", "IG Reels (9:16)", "IG Square (1:1)"]
        preset_menu = ttk.Combobox(toolbar, textvariable=self.preset_var, values=presets, state="readonly", width=20)
        preset_menu.pack(side=LEFT, padx=2)
        preset_menu.bind("<<ComboboxSelected>>", self._on_preset_change)
        ttk.Label(toolbar, text="Resolusi:").pack(side=LEFT, padx=(10, 2))
        self.resolution_var = tk.StringVar(value=self.project.output_resolution)
        self.resolution_menu = ttk.Combobox(toolbar, textvariable=self.resolution_var, state="readonly", width=12)
        self.resolution_menu.pack(side=LEFT, padx=2)
        self.resolution_menu.bind("<<ComboboxSelected>>", self._on_resolution_change)
        self._update_resolution_options()
        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y, ipady=5)
        ttk.Button(toolbar, text="⚙️ Diagnostics", command=self._show_diagnostics, style="info.Outline.TButton").pack(side=LEFT, padx=2)


    def _populate_export_tab(self, parent):
        ttk.Label(parent, text="Pengaturan Render", font="-weight bold").pack(anchor=W)
        
        # --- Target FPS (BARU) ---
        fps_frame = ttk.Frame(parent)
        fps_frame.pack(fill=X, pady=5)
        ttk.Label(fps_frame, text="Target FPS:", width=18).pack(side=LEFT)
        self.export_fps_var = tk.StringVar(value=self.export.target_fps)
        fps_combo = ttk.Combobox(fps_frame, textvariable=self.export_fps_var, values=["Auto", "24", "30", "60", "120"], state="readonly")
        fps_combo.pack(fill=X, expand=True)
        fps_combo.bind("<<ComboboxSelected>>", lambda e: setattr(self.export, 'target_fps', self.export_fps_var.get()))
        ToolTip(fps_combo, text=_("tooltip_fps"))

        # --- Kualitas CRF (BARU, Slider) ---
        crf_frame = ttk.Labelframe(parent, text=f"Kualitas (CRF: {self.export.crf})", padding=(10, 5))
        crf_frame.pack(fill=X, pady=5)
        self.export_crf_var = tk.IntVar(value=self.export.crf)
        
        def on_crf_change(value):
            val = int(float(value))
            self.export.crf = val
            crf_frame.config(text=f"Kualitas (CRF: {val})")

        crf_slider = ttk.Scale(crf_frame, from_=0, to=28, variable=self.export_crf_var, command=on_crf_change)
        crf_slider.pack(fill=X, pady=(0, 5))
        ToolTip(crf_slider, text=_("tooltip_crf"))

        labels_frame = ttk.Frame(crf_frame)
        labels_frame.pack(fill=X)
        labels = {"0": "Lossless", "18": "Bagus+", "23": "Hemat", "28": "Ringan"}
        for val, text in labels.items():
            ttk.Label(labels_frame, text=text).pack(side=LEFT, padx=5, expand=True)
        
        # --- Preset Kecepatan (BARU) ---
        preset_frame = ttk.Frame(parent)
        preset_frame.pack(fill=X, pady=5)
        ttk.Label(preset_frame, text="Preset (Kecepatan):", width=18).pack(side=LEFT)
        self.export_preset_var = tk.StringVar(value=self.export.preset)
        presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        preset_combo = ttk.Combobox(preset_frame, textvariable=self.export_preset_var, values=presets, state="readonly")
        preset_combo.pack(fill=X, expand=True)
        preset_combo.bind("<<ComboboxSelected>>", lambda e: setattr(self.export, 'preset', self.export_preset_var.get()))
        ToolTip(preset_combo, text=_("tooltip_preset"))

        # --- Video Codec (Dropdown yang sudah ada) ---
        codec_frame = ttk.Frame(parent)
        codec_frame.pack(fill=X, pady=5)
        ttk.Label(codec_frame, text="Video Codec:", width=18).pack(side=LEFT)
        self.export_codec_var = tk.StringVar(value=self.export.video_codec)
        codecs = ["libx264", "libx265", "h264_nvenc", "hevc_nvenc"]
        codec_combo = ttk.Combobox(codec_frame, textvariable=self.export_codec_var, values=codecs, state="readonly")
        codec_combo.pack(fill=X, expand=True)
        codec_combo.bind("<<ComboboxSelected>>", lambda e: setattr(self.export, 'video_codec', self.export_codec_var.get()))

        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)
        self.render_button = ttk.Button(parent, text="🚀 Render Video", command=self._start_render, style="success.TButton", state=DISABLED)
        self.render_button.pack(fill=X, ipady=10, pady=(10,2))
        self.cancel_button = ttk.Button(parent, text="❌ Cancel Render", command=self._cancel_render, style="danger.TButton", state=DISABLED)
        self.cancel_button.pack(fill=X, ipady=5)

    def _render_single_video(self, video1_path: str, output_path: str, is_batch: bool = False):
        try:
            # ... (UI update awal tidak berubah)
            self.queue_ui_update(self.file_progress_bar.config, value=0)
            self.queue_ui_update(self.status_label.config, text=_("status_rendering", file=Path(output_path).name))
            
            v1_clip = mp.VideoFileClip(video1_path)
            v2_clip = mp.VideoFileClip(self.project.video2_path)
            
            # --- Logika FPS (BARU) ---
            render_fps = v1_clip.fps
            if self.export.target_fps != "Auto":
                try:
                    render_fps = int(self.export.target_fps)
                except ValueError:
                    logger.warning(f"Nilai FPS tidak valid: {self.export.target_fps}. Kembali ke FPS sumber.")
            
            # ... (Looping/subclip video tidak berubah)
            target_duration = v1_clip.duration
            if v2_clip.duration < target_duration:
                v2_clip = v2_clip.fx(mp.vfx.loop, duration=target_duration)
                if v2_clip.audio: v2_clip.audio = v2_clip.audio.fx(audio_loop, duration=target_duration)
            else:
                v2_clip = v2_clip.subclip(0, target_duration)

            def make_frame(t):
                if self.cancel_render_event.is_set(): raise StopIteration("Render cancelled")
                progress = (t / target_duration) * 100
                self.queue_ui_update(self.file_progress_bar.config, value=progress)
                frame1_rgb = v1_clip.get_frame(t)
                frame2_rgb = v2_clip.get_frame(t)
                frame1_bgr = cv2.cvtColor(frame1_rgb, cv2.COLOR_RGB2BGR)
                frame2_bgr = cv2.cvtColor(frame2_rgb, cv2.COLOR_RGB2BGR)
                composite_bgr = self._composite_single_frame(frame1_bgr, frame2_bgr)
                return cv2.cvtColor(composite_bgr, cv2.COLOR_BGR2RGB)

            final_clip = mp.VideoClip(make_frame, duration=target_duration)
            final_audio = self._compose_audio(v1_clip.audio, v2_clip.audio)
            if final_audio:
                final_clip = final_clip.set_audio(final_audio)

            # --- Logika Parameter FFmpeg (BARU) ---
            codec = self.export.video_codec
            ffmpeg_params = []
            
            # Fallback jika NVENC tidak tersedia
            if "nvenc" in codec and not self.is_nvenc_available:
                logger.warning(f"Codec {codec} tidak tersedia, fallback ke libx264.")
                codec = "libx264"
                self.queue_ui_update(self.status_label.config, text=f"Warning: {codec} tidak ada, fallback ke CPU.")
            
            # Atur parameter CRF/CQ berdasarkan codec
            if "nvenc" in codec:
                # NVENC menggunakan -cq atau -qp untuk VBR, bukan -crf
                ffmpeg_params.extend(["-rc", "vbr", "-cq", str(self.export.crf)])
            else: # CPU codecs (libx264, libx265)
                ffmpeg_params.extend(["-crf", str(self.export.crf)])
            
            # Tambahkan preset
            ffmpeg_params.extend(["-preset", self.export.preset])

            final_clip.write_videofile(
                output_path, 
                fps=render_fps, # Menggunakan FPS yang sudah ditentukan
                codec=codec,
                audio_codec=self.export.audio_codec, 
                audio_bitrate=self.export.audio_bitrate,
                # preset=None, # Preset diatur manual via ffmpeg_params
                threads=4,
                ffmpeg_params=ffmpeg_params, 
                logger=None
            )
            v1_clip.close()
            v2_clip.close()

            if not is_batch: self.queue_ui_update(self._on_render_finish, True, output_path)
            return True
        except StopIteration:
            logger.warning(f"Render untuk {output_path} dibatalkan.")
            if not is_batch: self.queue_ui_update(self._on_render_finish, False, output_path)
            return False
        except Exception as e:
            logger.error(f"Error saat rendering {output_path}: {e}", exc_info=True)
            if not is_batch: self.queue_ui_update(self._on_render_finish, False, output_path)
            self.queue_ui_update(messagebox.showerror, "Error Rendering", f"Terjadi kesalahan: {e}")
            return False

    # -------------------------------------------------------------------------- #
    # SISA KODE (TIDAK BERUBAH DARI VERSI SEBELUMNYA)
    # Metode untuk UI, playback, interaksi PiP, save/load, dll. tetap sama.
    # -------------------------------------------------------------------------- #
    
    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self.root, orient=HORIZONTAL)
        main_pane.pack(fill=BOTH, expand=True, padx=10, pady=10)

        preview_panel = ttk.Frame(main_pane)
        self._create_top_toolbar(preview_panel)
        self.canvas = tk.Canvas(preview_panel, bg="black", highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)
        self._create_player_controls(preview_panel)
        self._create_status_bar(preview_panel)
        main_pane.add(preview_panel, weight=3)

        sidebar_panel = ttk.Frame(main_pane)
        self._create_sidebar(sidebar_panel)
        main_pane.add(sidebar_panel, weight=1)

    def _create_player_controls(self, parent):
        control_frame = ttk.Frame(parent, padding=5)
        control_frame.pack(fill=X)
        self.play_pause_btn = ttk.Button(control_frame, text="▶", command=self._toggle_play_pause, width=3)
        self.play_pause_btn.pack(side=LEFT, padx=(0, 5))
        self.time_label = ttk.Label(control_frame, text="00:00 / 00:00", width=15, anchor=E)
        self.time_label.pack(side=RIGHT, padx=(5, 0))
        self.timeline_var = tk.DoubleVar()
        self.timeline_slider = ttk.Scale(control_frame, from_=0, to=100, variable=self.timeline_var, command=self._on_seek)
        self.timeline_slider.pack(fill=X, expand=True, side=LEFT)
        self.timeline_slider.bind("<ButtonPress-1>", self._on_scrub_start)
        self.timeline_slider.bind("<ButtonRelease-1>", self._on_scrub_end)

    def _create_status_bar(self, parent):
        status_bar = ttk.Frame(parent, padding=(5, 2))
        status_bar.pack(fill=X)
        self.status_label = ttk.Label(status_bar, text="Selamat datang! Buka video untuk memulai.")
        self.status_label.pack(side=LEFT)

    def _create_sidebar(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=BOTH, expand=True)
        project_tab = ttk.Frame(notebook, padding=10)
        batch_tab = ttk.Frame(notebook, padding=10)
        pip_tab = ttk.Frame(notebook, padding=10)
        shape_tab = ttk.Frame(notebook, padding=10)
        audio_tab = ttk.Frame(notebook, padding=10)
        export_tab = ttk.Frame(notebook, padding=10)
        notebook.add(project_tab, text="Project")
        notebook.add(batch_tab, text="Batch")
        notebook.add(pip_tab, text="PiP/Layout")
        notebook.add(shape_tab, text="Shape & Style")
        notebook.add(audio_tab, text="Audio")
        notebook.add(export_tab, text="Export")
        self._populate_project_tab(project_tab)
        self._populate_batch_tab(batch_tab)
        self._populate_pip_tab(pip_tab)
        self._populate_shape_tab(shape_tab)
        self._populate_audio_tab(audio_tab)
        self._populate_export_tab(export_tab)
        
    def _populate_project_tab(self, parent):
        ttk.Label(parent, text="Project Files", font="-weight bold").pack(anchor=W)
        ttk.Button(parent, text="Simpan Project (.json)", command=self._save_project, style="info.TButton").pack(fill=X, pady=5)
        ttk.Button(parent, text="Muat Project (.json)", command=self._load_project, style="info.outline.TButton").pack(fill=X)
        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)
        
        ttk.Label(parent, text="Canvas Settings", font="-weight bold").pack(anchor=W, pady=(0, 5))
        fit_frame = ttk.Frame(parent)
        fit_frame.pack(fill=X, pady=2)
        ttk.Label(fit_frame, text="Fit Mode:", width=12).pack(side=LEFT)
        self.fit_mode_var = tk.StringVar(value=self.project.fit_mode)
        fit_combo = ttk.Combobox(fit_frame, textvariable=self.fit_mode_var, values=["Contain", "Cover"], state="readonly")
        fit_combo.pack(fill=X, expand=True)
        fit_combo.bind("<<ComboboxSelected>>", self._on_fit_mode_change)

        safe_area_frame = ttk.Labelframe(parent, text="Safe Area", padding=5)
        safe_area_frame.pack(fill=X, pady=10)
        self.safe_area_var = tk.BooleanVar(value=self.project.safe_area.enabled)
        ttk.Checkbutton(safe_area_frame, text="Enable", variable=self.safe_area_var, command=self._on_safe_area_toggle, style="primary.Roundtoggle.Toolbutton").pack(anchor=W)
        self.safe_area_margin_var = tk.IntVar(value=self.project.safe_area.margin_percent)
        self.safe_area_label = ttk.Label(safe_area_frame, text=f"Margin: {self.safe_area_margin_var.get()}%")
        self.safe_area_label.pack(anchor=W, pady=(5,0))
        safe_area_slider = ttk.Scale(safe_area_frame, from_=0, to=25, variable=self.safe_area_margin_var, command=self._on_safe_area_margin_change)
        safe_area_slider.pack(fill=X)
        ToolTip(safe_area_slider, text=_("tooltip_safe_area"))

        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)
        self.v1_title_label = ttk.Label(parent, text="Video 1 (Base)", font="-weight bold")
        self.v1_title_label.pack(anchor=W, pady=(10, 2))
        self.v1_path_label = ttk.Label(parent, text="Belum ada file...", wraplength=300)
        self.v1_path_label.pack(anchor=W)
        self.v1_info_label = ttk.Label(parent, text="Info: -")
        self.v1_info_label.pack(anchor=W)
        ttk.Label(parent, text="Video 2 (Reaction)", font="-weight bold").pack(anchor=W, pady=(10, 2))
        self.v2_path_label = ttk.Label(parent, text="Belum ada file...", wraplength=300)
        self.v2_path_label.pack(anchor=W)
        self.v2_info_label = ttk.Label(parent, text="Info: -")
        self.v2_info_label.pack(anchor=W)

    def _populate_batch_tab(self, parent):
        controls_frame = ttk.Frame(parent)
        controls_frame.pack(fill=X, pady=5)
        ttk.Button(controls_frame, text="Add Folder", command=self._open_folder_video1, style="primary.TButton").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(controls_frame, text="Remove", command=self._remove_from_batch, style="danger.Outline.TButton").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(controls_frame, text="Clear", command=self._clear_batch, style="danger.TButton").pack(side=LEFT, fill=X, expand=True, padx=2)
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=BOTH, expand=True, pady=10)
        self.batch_tree = ttk.Treeview(tree_frame, columns=("filename", "status"), show="headings", selectmode="extended")
        self.batch_tree.heading("filename", text="Filename")
        self.batch_tree.heading("status", text="Status")
        self.batch_tree.column("filename", width=200, anchor=W)
        self.batch_tree.column("status", width=80, anchor=CENTER)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=vsb.set)
        self.batch_tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)
        ttk.Label(parent, text="Current File Progress").pack(anchor=W, pady=(10,0))
        self.file_progress_bar = ttk.Progressbar(parent, orient=HORIZONTAL, mode='determinate')
        self.file_progress_bar.pack(fill=X, pady=2)
        ttk.Label(parent, text="Total Batch Progress").pack(anchor=W, pady=(5,0))
        self.total_progress_bar = ttk.Progressbar(parent, orient=HORIZONTAL, mode='determinate')
        self.total_progress_bar.pack(fill=X, pady=2)

    def _populate_pip_tab(self, parent):
        ttk.Label(parent, text="Posisi Preset", font="-weight bold").pack(anchor=W)
        pos_frame = ttk.Frame(parent)
        pos_frame.pack(fill=X, pady=5)
        presets = ["Kiri-Atas", "Kanan-Atas", "Kiri-Bawah", "Kanan-Bawah", "Tengah-Atas", "Tengah", "Tengah-Bawah"]
        for i, p in enumerate(presets):
            btn = ttk.Button(pos_frame, text=p, command=lambda pr=p: self._set_pip_preset_pos(pr))
            btn.grid(row=i//2, column=i%2, sticky="ew", padx=2, pady=2)
        pos_frame.grid_columnconfigure((0,1), weight=1)

        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)

        self.pip_scale_var = tk.DoubleVar(value=self.pip_layout.scale_percent)
        self.pip_scale_label = ttk.Label(parent, text=f"Ukuran PiP ({self.pip_scale_var.get():.0f}%)")
        self.pip_scale_label.pack(anchor=W)
        self.pip_scale_slider = ttk.Scale(parent, from_=5, to=90, variable=self.pip_scale_var, command=self._on_pip_scale_change)
        self.pip_scale_slider.pack(fill=X, pady=5)

        self.pip_rotation_var = tk.DoubleVar(value=self.pip_layout.rotation)
        self.pip_rotation_label = ttk.Label(parent, text=f"Rotasi ({self.pip_rotation_var.get():.0f}°)")
        self.pip_rotation_label.pack(anchor=W)
        ttk.Scale(parent, from_=-180, to=180, variable=self.pip_rotation_var, command=self._on_pip_transform_change).pack(fill=X, pady=5)

        self.pip_opacity_var = tk.DoubleVar(value=self.pip_layout.opacity)
        self.pip_opacity_label = ttk.Label(parent, text=f"Opacity ({self.pip_opacity_var.get():.0f}%)")
        self.pip_opacity_label.pack(anchor=W)
        ttk.Scale(parent, from_=0, to=100, variable=self.pip_opacity_var, command=self._on_pip_transform_change).pack(fill=X, pady=5)

        self.pip_lock_aspect_var = tk.BooleanVar(value=self.pip_layout.lock_aspect)
        ttk.Checkbutton(parent, text="Kunci Aspect Ratio", variable=self.pip_lock_aspect_var, command=self._on_pip_transform_change, style="primary.Roundtoggle.Toolbutton").pack(anchor=W, pady=10)

        shadow_frame = ttk.Labelframe(parent, text="Drop Shadow", padding=10)
        shadow_frame.pack(fill=X, pady=15)
        self.pip_shadow_enabled_var = tk.BooleanVar(value=self.pip_layout.shadow.enabled)
        ttk.Checkbutton(shadow_frame, text="Enable Shadow", variable=self.pip_shadow_enabled_var, command=self._on_pip_shadow_change, style="primary.Roundtoggle.Toolbutton").pack(anchor=W)

    def _populate_shape_tab(self, parent):
        ttk.Label(parent, text="Bentuk Mask PiP", font="-weight bold").pack(anchor=W)
        self.shape_var = tk.StringVar(value=self.shape_style.shape)
        shapes = ["Bulat (Circle)", "Kotak (Square)", "Rounded Rect", "Polygon", "Full (No Mask)"]
        shape_combo = ttk.Combobox(parent, textvariable=self.shape_var, values=shapes, state="readonly")
        shape_combo.pack(fill=X, pady=5)
        shape_combo.bind("<<ComboboxSelected>>", self._on_shape_change)

        self.shape_options_frame = ttk.Frame(parent)
        self.shape_options_frame.pack(fill=X, pady=5)
        self._update_shape_options()

        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)
        ttk.Label(parent, text="Stroke (Garis Tepi)", font="-weight bold").pack(anchor=W)
        stroke_frame = ttk.Frame(parent)
        stroke_frame.pack(fill=X, pady=5)
        ttk.Label(stroke_frame, text="Lebar (px):").pack(side=LEFT)
        self.stroke_width_var = tk.IntVar(value=self.shape_style.stroke_width)
        ttk.Spinbox(stroke_frame, from_=0, to=50, textvariable=self.stroke_width_var, command=self._on_stroke_change, width=5).pack(side=LEFT, padx=5)
        self.stroke_color_btn = ttk.Button(stroke_frame, text="Warna", command=self._choose_stroke_color, width=8)
        self.stroke_color_btn.pack(side=LEFT)
        self._update_stroke_color_button()

    def _populate_audio_tab(self, parent):
        ttk.Label(parent, text="Kontrol Audio", font="-weight bold").pack(anchor=W)
        self.v1_mute_var = tk.BooleanVar(value=self.audio.v1_mute)
        ttk.Checkbutton(parent, text="Mute Video 1 (Base)", variable=self.v1_mute_var, command=self._on_audio_change, style="primary.Roundtoggle.Toolbutton").pack(anchor=W, pady=5)
        self.v2_mute_var = tk.BooleanVar(value=self.audio.v2_mute)
        ttk.Checkbutton(parent, text="Mute Video 2 (Reaction)", variable=self.v2_mute_var, command=self._on_audio_change, style="primary.Roundtoggle.Toolbutton").pack(anchor=W, pady=5)
        ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=15)
        ttk.Label(parent, text="Mode Mixing", font="-weight bold").pack(anchor=W)
        self.audio_mode_var = tk.StringVar(value=self.audio.mode)
        modes = ["Base only", "Reaction only", "Mix"]
        for mode in modes:
            ttk.Radiobutton(parent, text=mode, variable=self.audio_mode_var, value=mode, command=self._on_audio_change).pack(anchor=W)
        self.mix_slider_frame = ttk.Frame(parent)
        self.mix_slider_frame.pack(fill=X, pady=5, padx=20)
        self.audio_mix_level_var = tk.DoubleVar(value=self.audio.mix_level)
        self.mix_level_label = ttk.Label(self.mix_slider_frame, text=f"V1 {100-self.audio_mix_level_var.get():.0f}% | V2 {self.audio_mix_level_var.get():.0f}%")
        self.mix_level_label.pack()
        ttk.Scale(self.mix_slider_frame, from_=0, to=100, variable=self.audio_mix_level_var, command=self._on_audio_change).pack(fill=X)
        self._update_audio_controls()
        
    def _bind_events(self):
        self.root.bind("<space>", self._toggle_play_pause)
        self.root.bind("<Left>", lambda e: self._seek_relative(-1))
        self.root.bind("<Right>", lambda e: self._seek_relative(1))
        self.root.bind("<Shift-Left>", lambda e: self._seek_relative(-5))
        self.root.bind("<Shift-Right>", lambda e: self._seek_relative(5))
        self.root.bind("<Home>", lambda e: self._seek_to_frame(0))
        self.root.bind("<End>", lambda e: self._seek_to_frame(self.timeline.total_frames - 1))
        self.root.bind("<s>", self._save_snapshot)
        self.root.bind("<Control-r>", self._start_render)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_pip_interaction_start)
        self.canvas.bind("<B1-Motion>", self._on_pip_interaction_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_pip_interaction_end)
        self.canvas.bind("<Motion>", self._on_mouse_move)

    def _open_single_video1(self):
        path = filedialog.askopenfilename(title="Pilih Satu File Video 1", filetypes=[("Video Files", "*.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")])
        if not path: return
        self.project.processing_mode = "Single"
        self.project.video1_paths = [path]
        self._load_video(1, path)
        self.v1_title_label.config(text="Video 1 (Base) - Single Mode")

    def _open_folder_video1(self):
        folder_path = filedialog.askdirectory(title="Pilih Folder Berisi Video 1")
        if not folder_path: return
        video_files = []
        supported_formats = ['*.mp4', '*.mov', '*.avi', '*.mkv']
        for fmt in supported_formats: video_files.extend(list(Path(folder_path).glob(fmt)))
        if not video_files:
            messagebox.showinfo("Info", f"Tidak ada file video yang didukung di folder:\n{folder_path}")
            return
        self.project.processing_mode = "Batch"
        self.project.video1_paths = sorted([str(p) for p in video_files])
        self._load_video(1, self.project.video1_paths[0])
        self.v1_title_label.config(text=f"Video 1 (Base) - Batch Mode ({len(video_files)} videos)")
        self._update_batch_treeview()

    def _open_video2(self):
        path = filedialog.askopenfilename(title="Pilih Video 2 (Reaction)", filetypes=[("Video Files", "*.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")])
        if not path: return
        self.project.video2_path = path
        self._load_video(2, path)

    def _load_video(self, num, path):
        if not Path(path).exists():
            messagebox.showerror("Error", f"File tidak ditemukan: {path}")
            return

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror("Error", f"Gagal membuka file video: {Path(path).name}")
            return

        meta = {
            "path": path, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), "fps": cap.get(cv2.CAP_PROP_FPS),
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
        meta["duration"] = meta["frames"] / meta["fps"] if meta["fps"] > 0 else 0

        if num == 1:
            if self.v1_cap: self.v1_cap.release()
            self.v1_cap, self.v1_meta = cap, meta
            if self.project.processing_mode == "Batch":
                 self.v1_path_label.config(text=f"Folder: {Path(path).parent.name} | Preview: {Path(path).name}")
            else:
                 self.v1_path_label.config(text=Path(path).name)
            self.v1_info_label.config(text=f"{meta['width']}x{meta['height']} @ {meta['fps']:.2f}fps, Dur: {meta['duration']:.2f}s")
            self._reset_timeline()
        else: # num == 2
            if self.v2_cap: self.v2_cap.release()
            self.v2_cap, self.v2_meta = cap, meta
            self.v2_path_label.config(text=Path(path).name)
            self.v2_info_label.config(text=f"{self.v2_meta['width']}x{self.v2_meta['height']} @ {self.v2_meta['fps']:.2f}fps, Dur: {self.v2_meta['duration']:.2f}s")
            self.aspect_ratio = self.v2_meta['width'] / self.v2_meta['height'] if self.v2_meta['height'] > 0 else 1.0
            self._update_pip_geometry_from_scale(recalculate_pos=True)

        if self.v1_cap and self.v2_cap:
            self.render_button.config(state=NORMAL)
            logger.info("Kedua video telah dimuat, preview siap.")
        
        self.request_preview_update(force=True)

    def _reset_timeline(self):
        self.timeline.is_playing = False
        self.timeline.current_frame = 0
        self.timeline.total_frames = self.v1_meta.get("frames", 0)
        self.timeline.duration_sec = self.v1_meta.get("duration", 0)
        self.timeline_slider.config(to=self.timeline.total_frames - 1)
        self.timeline_var.set(0)
        self._update_time_label()
        self.play_pause_btn.config(text="▶")

    def request_preview_update(self, force=False):
        if self._after_id_preview:
            self.root.after_cancel(self._after_id_preview)
        
        delay = 0 if force else 33 # Debounce by 33ms
        self._after_id_preview = self.root.after(delay, self._generate_preview_frame)

    def _generate_preview_frame(self):
        self._after_id_preview = None
        if not self.v1_cap or not self.v2_cap or self.rendering_process:
            return

        try:
            self.v1_cap.set(cv2.CAP_PROP_POS_FRAMES, self.timeline.current_frame)
            self.v2_cap.set(cv2.CAP_PROP_POS_FRAMES, self.timeline.current_frame)
            ret1, frame1 = self.v1_cap.read()
            ret2, frame2 = self.v2_cap.read()
            if not ret1:
                self.v1_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret1, frame1 = self.v1_cap.read()
            if not ret2:
                self.v2_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret2, frame2 = self.v2_cap.read()

            if ret1 and ret2:
                composite_frame = self._composite_single_frame(frame1, frame2)
                img = cv2.cvtColor(composite_frame, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(img)
                if not self.preview_queue.full():
                    self.preview_queue.put(img_pil)
        except Exception as e:
            logger.error(f"Error generating preview frame: {e}")

    def _update_preview_canvas(self):
        try:
            img_pil = self.preview_queue.get_nowait()
            disp_x, disp_y, disp_w, disp_h, _ = self._get_preview_display_rect()
            if disp_w > 0 and disp_h > 0:
                img_pil.thumbnail((disp_w, disp_h), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(image=img_pil)
                self.canvas.delete("all")
                self.canvas.create_image(disp_x, disp_y, anchor=NW, image=self.photo)
        except queue.Empty:
            pass
        self.canvas.delete("overlays")
        self._draw_overlays()
        self.root.after(33, self._update_preview_canvas)

    def _draw_overlays(self):
        disp_x, disp_y, disp_w, disp_h, scale = self._get_preview_display_rect()
        if scale == 0: return

        if self.project.safe_area.enabled:
            margin_px = int(disp_w * (self.project.safe_area.margin_percent / 100))
            self.canvas.create_rectangle(disp_x + margin_px, disp_y + margin_px, disp_x + disp_w - margin_px, disp_y + disp_h - margin_px, outline='cyan', dash=(5, 3), width=1, tags="overlays")

        if self.v2_cap:
            px, py, pw, ph = self._get_pip_display_rect(scale)
            self.canvas.create_rectangle(px, py, px + pw, py + ph, outline='yellow', width=1, tags="overlays")
            handle_size = 3
            for hx, hy in self._get_handle_positions(px, py, pw, ph):
                self.canvas.create_rectangle(hx - handle_size, hy - handle_size, hx + handle_size, hy + handle_size, fill='yellow', outline='black', tags="overlays")

    def _get_handle_positions(self, x, y, w, h):
        return [(x, y), (x + w, y), (x, y + h), (x + w, y + h), (x + w / 2, y), (x + w / 2, y + h), (x, y + h / 2), (x + w, y + h / 2)]

    def _preview_playback_manager(self):
        while True:
            if not self.timeline.is_playing or self.timeline.is_scrubbing or not self.v1_meta:
                time.sleep(0.05)
                continue

            if self.timeline.current_frame >= self.timeline.total_frames -1:
                self.queue_ui_update(self._toggle_play_pause)
                self.timeline.current_frame = 0
                continue
            
            self.timeline.current_frame += 1
            self.queue_ui_update(self.timeline_var.set, self.timeline.current_frame)
            self.queue_ui_update(self._update_time_label)
            self.request_preview_update()
            
            playback_fps = self.v1_meta.get("fps", 30)
            sleep_duration = 1.0 / playback_fps if playback_fps > 0 else 0.033
            time.sleep(sleep_duration)

    def _on_preset_change(self, event=None):
        preset = self.preset_var.get()
        self.project.output_preset = preset
        if "9:16" in preset: self.project.output_resolution = "1080x1920"
        elif "1:1" in preset: self.project.output_resolution = "1080x1080"
        else: self.project.output_resolution = "1920x1080"
        self.resolution_var.set(self.project.output_resolution)
        self._update_resolution_options()
        self._on_resolution_change()
        
    def _on_resolution_change(self, event=None):
        self.project.output_resolution = self.resolution_var.get()
        self._update_pip_geometry_from_scale(recalculate_pos=True)
        self.request_preview_update(force=True)

    def _update_resolution_options(self):
        preset = self.preset_var.get()
        if "9:16" in preset: resolutions = ["1080x1920", "720x1280"]
        elif "1:1" in preset: resolutions = ["1080x1080", "720x720"]
        else: resolutions = ["3840x2160", "1920x1080", "1280x720"]
        self.resolution_menu['values'] = resolutions

    def _toggle_play_pause(self, event=None):
        if not self.v1_cap or not self.v2_cap: return
        self.timeline.is_playing = not self.timeline.is_playing
        self.play_pause_btn.config(text="⏸" if self.timeline.is_playing else "▶")
        if self.timeline.is_playing:
            logger.info("Playback started.")
        else:
            logger.info("Playback paused.")

    def _seek_relative(self, seconds):
        if not self.v1_meta: return
        fps = self.v1_meta.get("fps", 30)
        target_frame = self.timeline.current_frame + int(seconds * fps)
        self._seek_to_frame(target_frame)

    def _seek_to_frame(self, frame_num):
        if self.timeline.total_frames == 0: return
        self.timeline.current_frame = max(0, min(int(frame_num), self.timeline.total_frames - 1))
        self.timeline_var.set(self.timeline.current_frame)
        self._update_time_label()
        self.request_preview_update(force=True)

    def _on_seek(self, value):
        if self.timeline.is_scrubbing:
            self._seek_to_frame(float(value))

    def _on_scrub_start(self, event=None):
        self.timeline.is_scrubbing = True
        if self.timeline.is_playing:
            self._toggle_play_pause()
            self._was_playing = True
        else:
            self._was_playing = False

    def _on_scrub_end(self, event=None):
        self.timeline.is_scrubbing = False
        if hasattr(self, '_was_playing') and self._was_playing:
            self._toggle_play_pause()
        self._seek_to_frame(self.timeline_slider.get())

    def _update_time_label(self):
        if not self.v1_meta: return
        fps = self.v1_meta.get('fps', 30)
        if fps == 0: return
        current_time_str = time.strftime('%M:%S', time.gmtime(self.timeline.current_frame / fps))
        total_time_str = time.strftime('%M:%S', time.gmtime(self.timeline.duration_sec))
        self.time_label.config(text=f"{current_time_str} / {total_time_str}")

    def _save_snapshot(self, event=None):
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if not path: return
        if not self.v1_cap or not self.v2_cap: return
        self.v1_cap.set(cv2.CAP_PROP_POS_FRAMES, self.timeline.current_frame)
        self.v2_cap.set(cv2.CAP_PROP_POS_FRAMES, self.timeline.current_frame)
        ret1, frame1 = self.v1_cap.read()
        ret2, frame2 = self.v2_cap.read()
        if ret1 and ret2:
            composite_frame = self._composite_single_frame(frame1, frame2)
            cv2.imwrite(path, composite_frame)
            logger.info(f"Snapshot saved to {path}")

    def _composite_single_frame(self, base_frame, pip_frame):
        out_w, out_h = self._get_output_dims()
        base_resized = self._resize_with_aspect(base_frame, out_w, out_h, self.project.fit_mode)
        output_frame = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        x_off, y_off = (out_w - base_resized.shape[1]) // 2, (out_h - base_resized.shape[0]) // 2
        output_frame[y_off:y_off+base_resized.shape[0], x_off:x_off+base_resized.shape[1]] = base_resized
        pip_w, pip_h = self.pip_layout.width, self.pip_layout.height
        if pip_w <= 0 or pip_h <= 0: return output_frame
        
        pip_resized = cv2.resize(pip_frame, (pip_w, pip_h), interpolation=cv2.INTER_AREA)
        
        inner_mask = self._create_pip_mask((pip_w, pip_h))
        full_mask = inner_mask.copy()
        
        final_pip_element = np.zeros((pip_h, pip_w, 3), dtype=np.uint8)

        if self.shape_style.stroke_width > 0:
            stroke_mask = self._create_pip_mask((pip_w, pip_h), is_stroke=True)
            stroke_color_bgr = tuple(int(self.shape_style.stroke_color.lstrip('#')[i:i+2], 16) for i in (4, 2, 0))
            final_pip_element[stroke_mask > 0] = stroke_color_bgr
            full_mask = cv2.bitwise_or(inner_mask, stroke_mask)
        
        final_pip_element[inner_mask > 0] = pip_resized[inner_mask > 0]
        
        x, y = self.pip_layout.x, self.pip_layout.y
        x1, y1 = max(x, 0), max(y, 0)
        x2, y2 = min(x + pip_w, out_w), min(y + pip_h, out_h)
        w_valid, h_valid = x2 - x1, y2 - y1

        if w_valid > 0 and h_valid > 0:
            pip_sub = final_pip_element[y1-y:y1-y+h_valid, x1-x:x1-x+w_valid]
            mask_sub = full_mask[y1-y:y1-y+h_valid, x1-x:x1-x+w_valid]
            roi = output_frame[y1:y2, x1:x2]
            mask_inv = cv2.bitwise_not(mask_sub)
            bg = cv2.bitwise_and(roi, roi, mask=mask_inv)
            fg = cv2.bitwise_and(pip_sub, pip_sub, mask=mask_sub)
            output_frame[y1:y2, x1:x2] = cv2.add(bg, fg)

        return output_frame

    def _create_pip_mask(self, size: Tuple[int, int], is_stroke=False) -> np.ndarray:
        w, h = size
        if w <= 0 or h <= 0: return np.zeros((h, w), dtype=np.uint8)
        
        stroke_width = self.shape_style.stroke_width if is_stroke else 0
        cache_key = (w, h, is_stroke, self.shape_style.shape, self.shape_style.corner_radius, self.shape_style.polygon_sides, stroke_width)
        if cache_key in self.mask_cache:
            return self.mask_cache[cache_key]
        
        img = Image.new('L', (w, h), 0)
        draw = ImageDraw.Draw(img)
        shape = self.shape_style.shape
        shape_box = [0, 0, w, h]

        if shape == "Full (No Mask)": draw.rectangle(shape_box, fill=255)
        elif shape == "Kotak (Square)":
            min_dim = min(w, h)
            offset_x, offset_y = (w - min_dim) // 2, (h - min_dim) // 2
            draw.rectangle([offset_x, offset_y, w - offset_x, h - offset_y], fill=255)
        elif shape == "Bulat (Circle)":
            min_dim = min(w, h)
            offset_x, offset_y = (w - min_dim) // 2, (h - min_dim) // 2
            draw.ellipse([offset_x, offset_y, w - offset_x, h - offset_y], fill=255)
        elif shape == "Rounded Rect": draw.rounded_rectangle(shape_box, radius=self.shape_style.corner_radius, fill=255)
        elif shape == "Polygon":
            sides, center_x, center_y, radius = self.shape_style.polygon_sides, w / 2, h / 2, min(w, h) / 2
            points = [(center_x + radius * math.cos(math.radians(360/sides*i - 90)), center_y + radius * math.sin(math.radians(360/sides*i - 90))) for i in range(sides)]
            draw.polygon(points, fill=255)

        mask = np.array(img)
        
        if is_stroke and self.shape_style.stroke_width > 0:
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(mask, kernel, iterations=int(self.shape_style.stroke_width / 1.5))
            result = cv2.subtract(dilated, mask)
            self.mask_cache[cache_key] = result
            return result
        
        self.mask_cache[cache_key] = mask
        return mask

    def _start_render(self, event=None):
        if not self.ffmpeg_path:
            self._show_ffmpeg_warning()
            return
        if self.rendering_process:
            messagebox.showwarning("Info", "Proses rendering lain sedang berjalan.")
            return

        self.cancel_render_event.clear()
        self.render_button.config(state=DISABLED)
        self.cancel_button.config(state=NORMAL)
        
        if self.project.processing_mode == "Batch":
            self._start_batch_render()
        else: # Single Mode
            output_path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 Video", "*.mp4")])
            if not output_path:
                self._on_render_finish(False, "")
                return
            
            video1_path = self.project.video1_paths[0]
            render_thread = threading.Thread(target=self._render_single_video, args=(video1_path, output_path, False), daemon=True, name="RenderThread")
            render_thread.start()

    def _start_batch_render(self):
        output_dir = filedialog.askdirectory(title="Pilih Folder Output untuk Hasil Batch")
        if not output_dir:
            self._on_render_finish(False, "")
            return
        self.project.output_dir = output_dir
        
        render_thread = threading.Thread(target=self._render_batch, daemon=True, name="RenderBatchThread")
        render_thread.start()

    def _render_batch(self):
        items = self.batch_tree.get_children()
        total_videos = len(items)
        self.queue_ui_update(self.total_progress_bar.config, value=0)

        for i, item_id in enumerate(items):
            if self.cancel_render_event.is_set():
                logger.info("Batch rendering dibatalkan.")
                break
            
            video1_path = self.batch_tree.item(item_id, 'values')[0]
            self.queue_ui_update(self.batch_tree.set, item_id, column="status", value="Running")
            
            output_filename = f"{Path(video1_path).stem}_reaction.mp4"
            output_path = str(Path(self.project.output_dir) / output_filename)
            
            success = self._render_single_video(video1_path, output_path, is_batch=True)
            
            status = "Done" if success else "Failed"
            self.queue_ui_update(self.batch_tree.set, item_id, column="status", value=status)
            self.queue_ui_update(self.total_progress_bar.config, value=(i + 1) / total_videos * 100)

        self.queue_ui_update(self._on_render_finish, True, self.project.output_dir) 
        if not self.cancel_render_event.is_set():
             self.queue_ui_update(messagebox.showinfo, "Sukses", _("status_batch_done", count=total_videos))

    def _cancel_render(self):
        if self.rendering_process or self.render_button['state'] == DISABLED:
             if messagebox.askyesno("Cancel Render", _("confirm_cancel_render")):
                logger.info("Mencoba membatalkan render...")
                self.cancel_render_event.set()
                if self.rendering_process:
                    self.rendering_process.terminate()
                self.status_label.config(text=_("status_render_cancelled"))
                self._on_render_finish(False, "")

    def _on_render_finish(self, success, output_path):
        self.rendering_process = None
        self.cancel_render_event.clear()
        self.render_button.config(state=NORMAL if self.v1_cap and self.v2_cap else DISABLED)
        self.cancel_button.config(state=DISABLED)
        if success and not Path(output_path).is_dir():
            self.status_label.config(text=_("status_render_done", file=Path(output_path).name))
        elif not success and output_path:
             self.status_label.config(text=_("status_render_error"))

    def _compose_audio(self, audio1, audio2):
        if self.audio.v1_mute: audio1 = None
        if self.audio.v2_mute: audio2 = None
        if not audio1 and not audio2: return None
        if not audio1: return audio2
        if not audio2: return audio1
        mode = self.audio.mode
        if mode == "Base only": return audio1
        if mode == "Reaction only": return audio2
        if mode == "Mix":
            level_v2 = self.audio.mix_level / 100.0
            return mp.CompositeAudioClip([audio1.volumex(1.0 - level_v2), audio2.volumex(level_v2)])
        return audio1
    
    def _get_output_dims(self) -> Tuple[int, int]:
        w_str, h_str = self.project.output_resolution.split('x')
        return int(w_str), int(h_str)

    def _resize_with_aspect(self, image, target_w, target_h, mode="Contain"):
        h, w = image.shape[:2]
        if w == 0 or h == 0: return np.zeros((target_h, target_w, 3), dtype=np.uint8)
        scale = min(target_w / w, target_h / h) if mode == "Contain" else max(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        if mode == "Cover":
            start_x, start_y = (new_w - target_w) // 2, (new_h - target_h) // 2
            return resized[start_y:start_y+target_h, start_x:start_x+target_w]
        return resized
    
    def _update_batch_treeview(self):
        self.batch_tree.delete(*self.batch_tree.get_children())
        for path in self.project.video1_paths:
            self.batch_tree.insert("", "end", values=(path, "Queued"))

    def _remove_from_batch(self):
        selected_items = self.batch_tree.selection()
        if not selected_items: return
        
        paths_to_remove = {self.batch_tree.item(item, 'values')[0] for item in selected_items}
        self.project.video1_paths = [p for p in self.project.video1_paths if p not in paths_to_remove]
        
        for item in selected_items: self.batch_tree.delete(item)
        
        self.v1_title_label.config(text=f"Video 1 (Base) - Batch Mode ({len(self.project.video1_paths)} videos)")

    def _clear_batch(self):
        self.project.video1_paths.clear()
        self.batch_tree.delete(*self.batch_tree.get_children())
        self.v1_title_label.config(text="Video 1 (Base) - Batch Mode (0 videos)")

    def _on_pip_scale_change(self, value=None):
        if value: self.pip_layout.scale_percent = float(value)
        self.pip_scale_label.config(text=f"Ukuran PiP ({self.pip_layout.scale_percent:.0f}%)")
        self._update_pip_geometry_from_scale()
        self.request_preview_update()

    def _on_pip_transform_change(self, value=None):
        self.pip_layout.rotation = self.pip_rotation_var.get()
        self.pip_layout.opacity = self.pip_opacity_var.get()
        self.pip_layout.lock_aspect = self.pip_lock_aspect_var.get()
        self.pip_rotation_label.config(text=f"Rotasi ({self.pip_layout.rotation:.0f}°)")
        self.pip_opacity_label.config(text=f"Opacity ({self.pip_layout.opacity:.0f}%)")
        self.request_preview_update()
        
    def _on_pip_shadow_change(self, value=None):
        self.pip_layout.shadow.enabled = self.pip_shadow_enabled_var.get()
        self.request_preview_update()

    def _on_shape_change(self, event=None):
        self.shape_style.shape = self.shape_var.get()
        self._update_shape_options()
        self.mask_cache.clear() 
        self.request_preview_update(force=True)

    def _update_shape_options(self):
        for widget in self.shape_options_frame.winfo_children(): widget.destroy()
        shape = self.shape_style.shape
        if shape == "Rounded Rect":
            ttk.Label(self.shape_options_frame, text="Radius Sudut:").pack(side=LEFT)
            self.shape_radius_var = tk.IntVar(value=self.shape_style.corner_radius)
            ttk.Spinbox(self.shape_options_frame, from_=0, to=100, textvariable=self.shape_radius_var, command=self._on_shape_param_change, width=5).pack(side=LEFT, padx=5)
        elif shape == "Polygon":
            ttk.Label(self.shape_options_frame, text="Jumlah Sisi:").pack(side=LEFT)
            self.shape_sides_var = tk.IntVar(value=self.shape_style.polygon_sides)
            ttk.Spinbox(self.shape_options_frame, from_=3, to=12, textvariable=self.shape_sides_var, command=self._on_shape_param_change, width=5).pack(side=LEFT, padx=5)

    def _on_shape_param_change(self):
        shape = self.shape_style.shape
        try:
            if shape == "Rounded Rect": self.shape_style.corner_radius = self.shape_radius_var.get()
            elif shape == "Polygon": self.shape_style.polygon_sides = self.shape_sides_var.get()
        except tk.TclError: pass
        self.mask_cache.clear()
        self.request_preview_update(force=True)

    def _on_stroke_change(self):
        try: self.shape_style.stroke_width = self.stroke_width_var.get()
        except tk.TclError: pass
        self.mask_cache.clear()
        self.request_preview_update(force=True)

    def _choose_stroke_color(self):
        color_code = colorchooser.askcolor(title="Pilih Warna Stroke", initialcolor=self.shape_style.stroke_color)
        if color_code and color_code[1]:
            self.shape_style.stroke_color = color_code[1]
            self._update_stroke_color_button()
            self.request_preview_update()

    def _update_stroke_color_button(self):
        style_name = f"{self.shape_style.stroke_color}.TButton"
        self.style.configure(style_name, background=self.shape_style.stroke_color)
        self.stroke_color_btn.config(style=style_name)

    def _on_audio_change(self, value=None):
        self.audio.v1_mute = self.v1_mute_var.get()
        self.audio.v2_mute = self.v2_mute_var.get()
        self.audio.mode = self.audio_mode_var.get()
        self.audio.mix_level = self.audio_mix_level_var.get()
        self._update_audio_controls()

    def _update_audio_controls(self):
        is_mix_mode = self.audio.mode == "Mix"
        state = NORMAL if is_mix_mode else DISABLED
        for child in self.mix_slider_frame.winfo_children():
            try: child.config(state=state)
            except tk.TclError: pass
        if is_mix_mode:
            self.mix_level_label.config(text=f"V1 {100-self.audio_mix_level_var.get():.0f}% | V2 {self.audio_mix_level_var.get():.0f}%")

    def _on_fit_mode_change(self, event=None):
        self.project.fit_mode = self.fit_mode_var.get()
        self.request_preview_update(force=True)

    def _on_safe_area_toggle(self, event=None):
        self.project.safe_area.enabled = self.safe_area_var.get()
        self.request_preview_update(force=True)

    def _on_safe_area_margin_change(self, value):
        self.project.safe_area.margin_percent = self.safe_area_margin_var.get()
        self.safe_area_label.config(text=f"Margin: {self.project.safe_area.margin_percent}%")
        self.request_preview_update(force=True)

    def _set_pip_preset_pos(self, preset):
        if not self.v2_meta: return
        self.pip_layout.pos_preset = preset
        out_w, out_h = self._get_output_dims()
        pip_w, pip_h = self.pip_layout.width, self.pip_layout.height
        margin = int(min(out_w, out_h) * 0.02)
        
        pos_map = {
            "Kiri-Atas": (margin, margin), "Kanan-Atas": (out_w - pip_w - margin, margin),
            "Kiri-Bawah": (margin, out_h - pip_h - margin), "Kanan-Bawah": (out_w - pip_w - margin, out_h - pip_h - margin),
            "Tengah-Atas": ((out_w - pip_w) // 2, margin), "Tengah": ((out_w - pip_w) // 2, (out_h - pip_h) // 2),
            "Tengah-Bawah": ((out_w - pip_w) // 2, out_h - pip_h - margin)
        }
        self.pip_layout.x, self.pip_layout.y = pos_map.get(preset, (self.pip_layout.x, self.pip_layout.y))
        self.request_preview_update()

    def _update_pip_geometry_from_scale(self, recalculate_pos=False):
        if not self.v2_meta: return
        out_w, out_h = self._get_output_dims()
        shorter_side = min(out_w, out_h)
        target_h = shorter_side * (self.pip_layout.scale_percent / 100.0)
        target_w = target_h * self.aspect_ratio
        self.pip_layout.width = int(target_w)
        self.pip_layout.height = int(target_h)
        if recalculate_pos:
            self._set_pip_preset_pos(self.pip_layout.pos_preset)

    def _get_preview_display_rect(self):
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        out_w, out_h = self._get_output_dims()
        if any(x == 0 for x in [canvas_w, canvas_h, out_w, out_h]): return 0, 0, 0, 0, 0.0
        scale = min(canvas_w / out_w, canvas_h / out_h)
        display_w, display_h = int(out_w * scale), int(out_h * scale)
        display_x, display_y = (canvas_w - display_w) // 2, (canvas_h - display_h) // 2
        return display_x, display_y, display_w, display_h, scale

    def _get_pip_display_rect(self, scale):
        disp_x_offset, disp_y_offset, _, _, _ = self._get_preview_display_rect()
        pip_disp_x = disp_x_offset + int(self.pip_layout.x * scale)
        pip_disp_y = disp_y_offset + int(self.pip_layout.y * scale)
        pip_disp_w = int(self.pip_layout.width * scale)
        pip_disp_h = int(self.pip_layout.height * scale)
        return pip_disp_x, pip_disp_y, pip_disp_w, pip_disp_h

    def _on_canvas_resize(self, event=None):
        self.request_preview_update()
        
    def _save_project(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Project Files", "*.json")])
        if not path: return
        full_state = {"project": asdict(self.project), "pip_layout": asdict(self.pip_layout), "shape_style": asdict(self.shape_style), "audio": asdict(self.audio), "export": asdict(self.export)}
        try:
            with open(path, 'w') as f: json.dump(full_state, f, indent=4)
            logger.info(f"Proyek disimpan ke {path}")
        except Exception as e: messagebox.showerror("Error", f"Gagal menyimpan proyek: {e}")

    def _load_project(self): pass

    def _on_pip_interaction_start(self, event):
        if not self.v2_cap: return
        _, _, _, _, scale = self._get_preview_display_rect()
        if scale == 0: return
        pip_rect = self._get_pip_display_rect(scale)
        self.active_handle = self._get_handle_at_pos(event.x, event.y, pip_rect)
        if self.active_handle: self.pip_interaction_mode = 'resizing'
        elif pip_rect[0] <= event.x <= pip_rect[0] + pip_rect[2] and pip_rect[1] <= event.y <= pip_rect[1] + pip_rect[3]:
            self.pip_interaction_mode = 'dragging'
        else:
            self.pip_interaction_mode = None
            return
        self.original_pip_geom = (self.pip_layout.x, self.pip_layout.y, self.pip_layout.width, self.pip_layout.height)
        self.drag_start_pos = (event.x, event.y)

    def _on_pip_interaction_move(self, event):
        if not self.pip_interaction_mode: return
        _, _, _, _, scale = self._get_preview_display_rect()
        if scale == 0: return
        dx = (event.x - self.drag_start_pos[0]) / scale
        dy = (event.y - self.drag_start_pos[1]) / scale
        ox, oy, ow, oh = self.original_pip_geom

        if self.pip_interaction_mode == 'dragging':
            self.pip_layout.x, self.pip_layout.y = int(ox + dx), int(oy + dy)
        elif self.pip_interaction_mode == 'resizing':
            new_w, new_h, new_x, new_y = ow, oh, ox, oy
            if 'left' in self.active_handle: new_x, new_w = ox + dx, ow - dx
            elif 'right' in self.active_handle: new_w = ow + dx
            if 'top' in self.active_handle: new_y, new_h = oy + dy, oh - dy
            elif 'bottom' in self.active_handle: new_h = oh + dy

            if self.pip_layout.lock_aspect:
                if 'right' in self.active_handle or 'left' in self.active_handle: new_h = new_w / self.aspect_ratio
                else: new_w = new_h * self.aspect_ratio
                if 'top' in self.active_handle: new_y = oy + (oh - new_h)
                if 'left' in self.active_handle: new_x = ox + (ow - new_w)

            if new_w > 20 and new_h > 20:
                self.pip_layout.x, self.pip_layout.y = int(new_x), int(new_y)
                self.pip_layout.width, self.pip_layout.height = int(new_w), int(new_h)
        
        self.request_preview_update()

    def _on_pip_interaction_end(self, event):
        self.pip_interaction_mode, self.active_handle = None, None
        self.canvas.config(cursor="")

    def _on_mouse_move(self, event):
        if self.pip_interaction_mode: return
        _, _, _, _, scale = self._get_preview_display_rect()
        if scale == 0:
            self.canvas.config(cursor="")
            return

        pip_rect = self._get_pip_display_rect(scale)
        handle = self._get_handle_at_pos(event.x, event.y, pip_rect)
        cursor_map = {
            'top-left': 'size_nw_se', 'bottom-right': 'size_nw_se', 'top-right': 'size_ne_sw',
            'bottom-left': 'size_ne_sw', 'top': 'sb_v_double_arrow', 'bottom': 'sb_v_double_arrow',
            'left': 'sb_h_double_arrow', 'right': 'sb_h_double_arrow',
        }
        new_cursor = cursor_map.get(handle, "")
        if not handle and (pip_rect[0] <= event.x <= pip_rect[0] + pip_rect[2] and pip_rect[1] <= event.y <= pip_rect[1] + pip_rect[3]):
            new_cursor = "fleur"

        if self.canvas.cget('cursor') != new_cursor:
            self.canvas.config(cursor=new_cursor)

    def _get_handle_at_pos(self, x, y, pip_rect):
        px, py, pw, ph = pip_rect
        handle_size = 8
        positions = self._get_handle_positions(px, py, pw, ph)
        names = ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'top', 'bottom', 'left', 'right']
        for name, (hx, hy) in zip(names, positions):
            if (hx - handle_size <= x <= hx + handle_size) and (hy - handle_size <= y <= hy + handle_size):
                return name
        return None

if __name__ == "__main__":
    root = ttkb.Window(themename="darkly")
    app = ReactionVideoMakerApp(root)
    root.mainloop()

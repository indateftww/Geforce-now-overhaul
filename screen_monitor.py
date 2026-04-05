"""Screen Monitor / Overwatch for Cyberpunk 2077 Companion.

Periodically captures screenshots of the GeForce Now window and detects
game state: breach protocol, map, dialogue, or normal gameplay.
Uses OCR and color analysis to classify screen regions.
"""

import threading
import time
import re
import io
import base64
from datetime import datetime

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    from PIL import Image, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except (ImportError, Exception):
    HAS_TESSERACT = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# Hex values used in breach protocol
BREACH_HEX_VALUES = {"1C", "55", "BD", "E9", "FF", "7A"}
BREACH_KEYWORDS = {"CODE MATRIX", "BUFFER", "SEQUENCE", "BREACH", "DAEMON", "UPLOAD"}
DIALOGUE_INDICATORS = {"[", "]"}  # Dialogue options often bracketed


class GameState:
    """Represents the detected state of the game screen."""
    IDLE = "idle"
    BREACH_PROTOCOL = "breach_protocol"
    MAP_OPEN = "map_open"
    DIALOGUE = "dialogue"
    GAMEPLAY = "gameplay"
    UNKNOWN = "unknown"


class ScreenMonitor:
    """Background screen monitor that detects Cyberpunk 2077 game states."""

    def __init__(self):
        self.active = False
        self.interval = 2.0  # seconds between captures
        self.thread = None
        self.state = GameState.IDLE
        self.last_screenshot = None
        self.last_screenshot_time = None
        self.last_ocr_text = ""
        self.region = None  # (x, y, width, height) or None for full screen
        self.breach_data = None  # Extracted breach protocol data
        self.dialogue_data = None  # Extracted dialogue options
        self.history = []  # Last 10 state changes
        self._lock = threading.Lock()
        self._callbacks = {
            "breach_detected": [],
            "dialogue_detected": [],
            "map_detected": [],
            "state_changed": [],
        }

    @property
    def capabilities(self):
        """Report which features are available based on installed packages."""
        return {
            "screenshot": HAS_PYAUTOGUI,
            "ocr": HAS_TESSERACT,
            "image_processing": HAS_PIL,
            "computer_vision": HAS_CV2,
        }

    def on(self, event, callback):
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event, data=None):
        """Emit an event to all registered callbacks."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass

    def set_region(self, x, y, width, height):
        """Set the screen capture region (for GeForce Now window)."""
        self.region = (x, y, width, height)

    def start(self):
        """Start the background monitoring loop."""
        if not HAS_PYAUTOGUI:
            return {"ok": False, "error": "pyautogui not installed"}
        if self.active:
            return {"ok": False, "error": "Already running"}

        self.active = True
        self.state = GameState.UNKNOWN
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        return {"ok": True, "status": "started"}

    def stop(self):
        """Stop the background monitoring loop."""
        self.active = False
        self.state = GameState.IDLE
        self.breach_data = None
        self.dialogue_data = None
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
        return {"ok": True, "status": "stopped"}

    def _monitor_loop(self):
        """Main monitoring loop running in background thread."""
        while self.active:
            try:
                self._capture_and_analyze()
            except Exception as e:
                # Don't crash the monitor on errors
                pass
            time.sleep(self.interval)

    def _capture_and_analyze(self):
        """Take a screenshot and analyze it for game state."""
        screenshot = self._take_screenshot()
        if screenshot is None:
            return

        with self._lock:
            self.last_screenshot = screenshot
            self.last_screenshot_time = datetime.now().isoformat()

        # Analyze the screenshot
        new_state = self._detect_state(screenshot)

        if new_state != self.state:
            old_state = self.state
            self.state = new_state

            # Track history
            self.history.append({
                "from": old_state,
                "to": new_state,
                "time": datetime.now().isoformat(),
            })
            if len(self.history) > 10:
                self.history.pop(0)

            self._emit("state_changed", {"from": old_state, "to": new_state})

            # Specific event callbacks
            if new_state == GameState.BREACH_PROTOCOL:
                self._extract_breach_data(screenshot)
                self._emit("breach_detected", self.breach_data)
            elif new_state == GameState.DIALOGUE:
                self._extract_dialogue_data(screenshot)
                self._emit("dialogue_detected", self.dialogue_data)
            elif new_state == GameState.MAP_OPEN:
                self._emit("map_detected", None)

    def _take_screenshot(self):
        """Capture a screenshot of the specified region or full screen."""
        if not HAS_PYAUTOGUI:
            return None
        try:
            if self.region:
                img = pyautogui.screenshot(region=self.region)
            else:
                img = pyautogui.screenshot()
            return img
        except Exception:
            return None

    def _detect_state(self, screenshot):
        """Analyze screenshot to determine game state."""
        # Strategy: Use a combination of color analysis and OCR

        # 1. Color histogram analysis (fast, no OCR needed)
        state_from_color = self._analyze_colors(screenshot)
        if state_from_color in (GameState.BREACH_PROTOCOL, GameState.MAP_OPEN):
            return state_from_color

        # 2. OCR analysis for text-based detection
        if HAS_TESSERACT:
            state_from_ocr = self._analyze_text(screenshot)
            if state_from_ocr != GameState.UNKNOWN:
                return state_from_ocr

        return state_from_color if state_from_color != GameState.UNKNOWN else GameState.GAMEPLAY

    def _analyze_colors(self, screenshot):
        """Detect game state from color patterns.

        Breach Protocol: Distinctive green/yellow matrix on dark background
        Map: Cyan/yellow map markers on dark background
        Dialogue: Dark bottom section with yellow text
        """
        if not HAS_PIL:
            return GameState.UNKNOWN

        img = screenshot
        width, height = img.size

        # Sample regions for analysis
        # Breach protocol has a distinctive grid in the center-left
        # with yellow/green hex values on dark background

        # Get color statistics for different regions
        top_region = img.crop((0, 0, width, height // 3))
        mid_region = img.crop((0, height // 3, width, 2 * height // 3))
        bottom_region = img.crop((0, 2 * height // 3, width, height))

        # Analyze mid region for breach protocol (green/yellow on dark)
        mid_colors = self._get_dominant_colors(mid_region)

        # Check for breach protocol: high concentration of specific green/yellow
        # The breach UI uses distinctive yellowy-green (#00ff00-ish) text
        green_yellow_ratio = mid_colors.get("green_yellow", 0)
        dark_ratio = mid_colors.get("dark", 0)

        if green_yellow_ratio > 0.05 and dark_ratio > 0.70:
            # Likely breach protocol - dark background with green/yellow text
            # Do OCR verification if available
            return GameState.BREACH_PROTOCOL

        # Check for map: cyan markers and road lines
        cyan_ratio = mid_colors.get("cyan", 0)
        if cyan_ratio > 0.03 and dark_ratio > 0.60:
            return GameState.MAP_OPEN

        # Check bottom region for dialogue (yellow text at bottom)
        bottom_colors = self._get_dominant_colors(bottom_region)
        yellow_ratio = bottom_colors.get("yellow", 0)
        if yellow_ratio > 0.02 and bottom_colors.get("dark", 0) > 0.50:
            return GameState.DIALOGUE

        return GameState.UNKNOWN

    def _get_dominant_colors(self, img):
        """Analyze an image region for color ratios relevant to CP2077 UI."""
        # Resize for speed, convert to RGB (screenshots may be RGBA)
        small = img.convert("RGB").resize((100, 100))
        pixels = list(small.getdata())
        total = len(pixels)

        categories = {
            "dark": 0,
            "green_yellow": 0,
            "cyan": 0,
            "yellow": 0,
            "red": 0,
            "other": 0,
        }

        for r, g, b in pixels:
            brightness = (r + g + b) / 3

            if brightness < 40:
                categories["dark"] += 1
            elif g > 150 and r < 100 and b < 100:
                categories["green_yellow"] += 1
            elif g > 150 and r > 150 and b < 80:
                categories["yellow"] += 1
            elif b > 180 and g > 180 and r < 80:
                categories["cyan"] += 1
            elif r > 200 and g < 80 and b < 80:
                categories["red"] += 1
            else:
                categories["other"] += 1

        # Convert to ratios
        return {k: v / total for k, v in categories.items()}

    def _analyze_text(self, screenshot):
        """Use OCR to detect game state from visible text."""
        if not HAS_TESSERACT or not HAS_PIL:
            return GameState.UNKNOWN

        try:
            # Pre-process: increase contrast, resize for better OCR
            img = screenshot.convert("L")  # Grayscale
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

            text = pytesseract.image_to_string(img, config="--psm 6")
            self.last_ocr_text = text
            text_upper = text.upper()

            # Check for breach protocol keywords
            breach_score = sum(1 for kw in BREACH_KEYWORDS if kw in text_upper)
            if breach_score >= 2:
                return GameState.BREACH_PROTOCOL

            # Check for hex values (strong indicator of breach protocol)
            hex_matches = re.findall(r'\b([0-9A-F]{2})\b', text_upper)
            hex_set = set(hex_matches)
            breach_hex_count = len(hex_set & BREACH_HEX_VALUES)
            if breach_hex_count >= 3 and len(hex_matches) > 10:
                return GameState.BREACH_PROTOCOL

            # Check for map indicators
            if any(kw in text_upper for kw in ["FAST TRAVEL", "SCANNER", "NCPD", "WAYPOINT"]):
                return GameState.MAP_OPEN

            # Check for dialogue indicators
            # CP2077 dialogue options are usually short lines with response options
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            short_lines = [l for l in lines if 5 < len(l) < 80]
            if len(short_lines) >= 3:
                # Could be dialogue options
                return GameState.DIALOGUE

        except Exception:
            pass

        return GameState.UNKNOWN

    def _extract_breach_data(self, screenshot):
        """Try to extract the breach protocol matrix from a screenshot."""
        if not HAS_TESSERACT or not HAS_PIL:
            self.breach_data = {"detected": True, "extracted": False}
            return

        try:
            width, height = screenshot.size

            # Breach protocol layout:
            # Left ~60% = code matrix
            # Right ~40% = target sequences
            # Top ~15% = buffer display

            # Extract matrix region (left side, middle area)
            matrix_region = screenshot.crop((
                int(width * 0.05),
                int(height * 0.20),
                int(width * 0.55),
                int(height * 0.85)
            ))

            # Extract sequence region (right side)
            seq_region = screenshot.crop((
                int(width * 0.55),
                int(height * 0.15),
                int(width * 0.95),
                int(height * 0.50)
            ))

            # OCR the matrix
            matrix_img = matrix_region.convert("L")
            matrix_img = ImageEnhance.Contrast(matrix_img).enhance(2.5)
            matrix_text = pytesseract.image_to_string(matrix_img, config="--psm 6")

            # Parse hex values from matrix text
            hex_values = re.findall(r'\b([0-9A-Fa-f]{2})\b', matrix_text)

            # OCR the sequences
            seq_img = seq_region.convert("L")
            seq_img = ImageEnhance.Contrast(seq_img).enhance(2.5)
            seq_text = pytesseract.image_to_string(seq_img, config="--psm 6")
            seq_hex = re.findall(r'\b([0-9A-Fa-f]{2})\b', seq_text)

            # Try to arrange into a grid (guess size from count)
            count = len(hex_values)
            grid_size = 0
            for s in [5, 6, 7]:
                if abs(count - s * s) <= s:
                    grid_size = s
                    break

            matrix = []
            if grid_size > 0:
                for r in range(grid_size):
                    row = []
                    for c in range(grid_size):
                        idx = r * grid_size + c
                        if idx < len(hex_values):
                            row.append(hex_values[idx].upper())
                        else:
                            row.append("00")
                    matrix.append(row)

            # Try to split sequences (each line is a sequence)
            sequences = []
            seq_lines = [l.strip() for l in seq_text.split("\n") if l.strip()]
            for line in seq_lines:
                vals = re.findall(r'\b([0-9A-Fa-f]{2})\b', line)
                if vals:
                    sequences.append([v.upper() for v in vals])

            self.breach_data = {
                "detected": True,
                "extracted": bool(matrix),
                "matrix": matrix,
                "sequences": sequences,
                "grid_size": grid_size,
                "raw_hex": [v.upper() for v in hex_values],
            }

        except Exception as e:
            self.breach_data = {
                "detected": True,
                "extracted": False,
                "error": str(e),
            }

    def _extract_dialogue_data(self, screenshot):
        """Try to extract dialogue options from a screenshot."""
        if not HAS_TESSERACT or not HAS_PIL:
            self.dialogue_data = {"detected": True, "extracted": False}
            return

        try:
            width, height = screenshot.size

            # Dialogue options typically appear in the bottom-right area
            dialog_region = screenshot.crop((
                int(width * 0.45),
                int(height * 0.55),
                int(width * 0.95),
                int(height * 0.95)
            ))

            img = dialog_region.convert("L")
            img = ImageEnhance.Contrast(img).enhance(2.0)
            text = pytesseract.image_to_string(img, config="--psm 6")

            # Parse dialogue options
            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]

            self.dialogue_data = {
                "detected": True,
                "extracted": bool(lines),
                "options": lines,
                "raw_text": text,
            }

        except Exception as e:
            self.dialogue_data = {
                "detected": True,
                "extracted": False,
                "error": str(e),
            }

    def get_state(self):
        """Get current monitor state as a JSON-serializable dict."""
        with self._lock:
            screenshot_b64 = None
            if self.last_screenshot and HAS_PIL:
                try:
                    buf = io.BytesIO()
                    # Resize for transmission
                    thumb = self.last_screenshot.resize((320, 180))
                    thumb.save(buf, format="JPEG", quality=60)
                    screenshot_b64 = base64.b64encode(buf.getvalue()).decode()
                except Exception:
                    pass

        return {
            "active": self.active,
            "state": self.state,
            "last_capture": self.last_screenshot_time,
            "capabilities": self.capabilities,
            "breach_data": self.breach_data,
            "dialogue_data": self.dialogue_data,
            "history": self.history[-5:],
            "thumbnail": screenshot_b64,
            "ocr_text": self.last_ocr_text[:500] if self.last_ocr_text else "",
            "interval": self.interval,
        }

    def take_single_screenshot(self):
        """Take a single screenshot and analyze it (on-demand, not background)."""
        if not HAS_PYAUTOGUI:
            return {"ok": False, "error": "pyautogui not installed"}

        screenshot = self._take_screenshot()
        if screenshot is None:
            return {"ok": False, "error": "Failed to capture screenshot"}

        with self._lock:
            self.last_screenshot = screenshot
            self.last_screenshot_time = datetime.now().isoformat()

        state = self._detect_state(screenshot)
        self.state = state

        if state == GameState.BREACH_PROTOCOL:
            self._extract_breach_data(screenshot)
        elif state == GameState.DIALOGUE:
            self._extract_dialogue_data(screenshot)

        return {
            "ok": True,
            "state": state,
            "breach_data": self.breach_data,
            "dialogue_data": self.dialogue_data,
        }


# Singleton monitor instance
monitor = ScreenMonitor()

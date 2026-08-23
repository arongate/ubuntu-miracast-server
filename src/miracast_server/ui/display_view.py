"""Display view for the Ubuntu Miracast Server.

Shows the current streaming state: idle (waiting), connected (negotiating),
or receiving (video display).
"""

import logging
from enum import Enum

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

logger = logging.getLogger(__name__)


class DisplayState(Enum):
    """Display view states."""

    IDLE = "idle"
    CONNECTED = "connected"
    RECEIVING = "receiving"


class DisplayView(Gtk.Box):
    """Main display view showing stream status and video output.

    States:
      - Idle: Centered icon + "Waiting for Miracast source..." + device name
      - Connected: "Source connected, waiting for stream..." + source name
      - Receiving: Gtk.Picture bound to gtk4paintablesink paintable
    """

    def __init__(self, receiver):
        """Initialize the display view.

        Args:
            receiver: MiracastReceiver instance for pipeline access.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._receiver = receiver
        self._state = DisplayState.IDLE
        self._fullscreen_controls_timeout: int | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        # Overlay for fullscreen controls
        self._overlay = Gtk.Overlay()
        self._overlay.set_vexpand(True)
        self._overlay.set_hexpand(True)
        self.append(self._overlay)

        # Stack for different states
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._overlay.set_child(self._stack)

        # ─── Idle view ────────────────────────────────────────────────
        idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        idle_box.set_valign(Gtk.Align.CENTER)
        idle_box.set_halign(Gtk.Align.CENTER)

        idle_icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        idle_icon.set_pixel_size(96)
        idle_icon.add_css_class("dim-label")
        idle_box.append(idle_icon)

        self._idle_label = Gtk.Label(label="Waiting for Miracast source...")
        self._idle_label.add_css_class("title-2")
        idle_box.append(self._idle_label)

        self._device_name_label = Gtk.Label(label="")
        self._device_name_label.add_css_class("dim-label")
        idle_box.append(self._device_name_label)

        # PIN display (persistent, not a dialog)
        self._pin_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._pin_box.set_margin_top(24)
        self._pin_box.set_halign(Gtk.Align.CENTER)

        pin_label_header = Gtk.Label(label="Enter this PIN on your device:")
        pin_label_header.add_css_class("dim-label")
        self._pin_box.append(pin_label_header)

        self._pin_label = Gtk.Label(label="")
        self._pin_label.add_css_class("title-1")
        self._pin_label.set_selectable(True)
        self._pin_box.append(self._pin_label)

        # Refresh PIN button
        self._refresh_pin_btn = Gtk.Button(label="Refresh PIN")
        self._refresh_pin_btn.set_halign(Gtk.Align.CENTER)
        self._refresh_pin_btn.set_margin_top(12)
        self._refresh_pin_btn.connect("clicked", self._on_refresh_pin_clicked)
        self._pin_box.append(self._refresh_pin_btn)

        self._pin_box.set_visible(False)
        idle_box.append(self._pin_box)

        self._stack.add_named(idle_box, DisplayState.IDLE.value)

        # ─── Connected view ───────────────────────────────────────────
        connected_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        connected_box.set_valign(Gtk.Align.CENTER)
        connected_box.set_halign(Gtk.Align.CENTER)

        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        spinner.set_size_request(48, 48)
        connected_box.append(spinner)

        self._connected_label = Gtk.Label(label="Source connected, waiting for stream...")
        self._connected_label.add_css_class("title-3")
        connected_box.append(self._connected_label)

        self._source_name_label = Gtk.Label(label="")
        self._source_name_label.add_css_class("dim-label")
        connected_box.append(self._source_name_label)

        self._stack.add_named(connected_box, DisplayState.CONNECTED.value)

        # ─── Receiving view ───────────────────────────────────────────
        receiving_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        receiving_box.set_vexpand(True)

        self._video_picture = Gtk.Picture()
        self._video_picture.set_vexpand(True)
        self._video_picture.set_hexpand(True)
        self._video_picture.set_can_shrink(True)
        receiving_box.append(self._video_picture)

        self._stack.add_named(receiving_box, DisplayState.RECEIVING.value)

        # ─── Fullscreen overlay controls ──────────────────────────────
        self._controls_revealer = Gtk.Revealer()
        self._controls_revealer.set_valign(Gtk.Align.END)
        self._controls_revealer.set_halign(Gtk.Align.CENTER)
        self._controls_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._overlay.add_overlay(self._controls_revealer)

        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls_box.add_css_class("toolbar")
        controls_box.add_css_class("osd")
        controls_box.set_margin_bottom(24)
        self._controls_revealer.set_child(controls_box)

        disconnect_btn = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        disconnect_btn.set_tooltip_text("Disconnect")
        disconnect_btn.connect("clicked", self._on_disconnect_clicked)
        controls_box.append(disconnect_btn)

        fullscreen_btn = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic")
        fullscreen_btn.set_tooltip_text("Toggle Fullscreen")
        fullscreen_btn.connect("clicked", self._on_fullscreen_clicked)
        controls_box.append(fullscreen_btn)

        # ─── Stats overlay (top-right) ───────────────────────────────
        self._stats_revealer = Gtk.Revealer()
        self._stats_revealer.set_valign(Gtk.Align.START)
        self._stats_revealer.set_halign(Gtk.Align.END)
        self._stats_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self._overlay.add_overlay(self._stats_revealer)

        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        stats_box.add_css_class("osd")
        stats_box.set_margin_top(8)
        stats_box.set_margin_end(8)
        self._stats_revealer.set_child(stats_box)

        self._stats_label = Gtk.Label(label="")
        self._stats_label.set_xalign(1.0)
        self._stats_label.add_css_class("caption")
        stats_box.append(self._stats_label)

        # Mouse motion controller for showing controls
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_mouse_motion)
        self.add_controller(motion)

        # Keyboard controller for fullscreen toggle — attached to widget
        # NOTE: The primary fullscreen key handler is at the window level
        # (see MainWindow) to ensure it works regardless of focus.

        # Double-click for fullscreen
        gesture = Gtk.GestureClick()
        gesture.set_button(1)
        gesture.connect("released", self._on_double_click)
        self._video_picture.add_controller(gesture)

    def set_state_idle(self, device_name: str = "") -> None:
        """Transition to idle state."""
        self._state = DisplayState.IDLE
        self._device_name_label.set_text(f"Discoverable as: {device_name}" if device_name else "")
        self._stack.set_visible_child_name(DisplayState.IDLE.value)
        self._stats_revealer.set_reveal_child(False)
        self._controls_revealer.set_reveal_child(False)

    def set_pin(self, pin: str) -> None:
        """Display the WPS PIN persistently in the idle view."""
        self._pin_label.set_text(pin)
        self._pin_box.set_visible(True)

    def hide_pin(self) -> None:
        """Hide the PIN display."""
        self._pin_box.set_visible(False)
        self._pin_label.set_text("")

    def _on_refresh_pin_clicked(self, button: Gtk.Button) -> None:
        """Handle Refresh PIN button — request new PIN from connection handler."""
        window = self.get_root()
        if window and hasattr(window, "connection_handler"):
            window.connection_handler.rearm_wps_pin()

    def set_state_connected(self, source_name: str) -> None:
        """Transition to connected state."""
        self._state = DisplayState.CONNECTED
        self._source_name_label.set_text(source_name)
        self._stack.set_visible_child_name(DisplayState.CONNECTED.value)

    def set_state_receiving(self) -> None:
        """Transition to receiving state, binding the video paintable."""
        self._state = DisplayState.RECEIVING
        self._stack.set_visible_child_name(DisplayState.RECEIVING.value)
        self._stats_revealer.set_reveal_child(True)

        # Bind the paintable from the GStreamer pipeline
        if self._receiver.pipeline:
            videosink = self._receiver.pipeline.get_by_name("videosink")
            if videosink:
                try:
                    paintable = videosink.get_property("paintable")
                    if paintable:
                        self._video_picture.set_paintable(paintable)
                except Exception as e:
                    logger.warning("Could not bind paintable: %s", e)

    def update_stats(self, stats: dict) -> None:
        """Update the stats overlay display."""
        if self._state != DisplayState.RECEIVING:
            return

        resolution = stats.get("resolution", (0, 0))
        bitrate = stats.get("bitrate", 0)
        duration = stats.get("duration", 0)

        bitrate_mbps = bitrate / 1_000_000 if bitrate else 0
        res_str = f"{resolution[0]}x{resolution[1]}" if resolution[0] > 0 else "Unknown"

        minutes = duration // 60
        seconds = duration % 60

        text = f"{res_str} | {bitrate_mbps:.1f} Mbps | {minutes}:{seconds:02d}"
        self._stats_label.set_text(text)

    def _on_disconnect_clicked(self, button: Gtk.Button) -> None:
        """Handle disconnect button click."""
        window = self.get_root()
        if window and hasattr(window, "connection_handler"):
            window.connection_handler.disconnect_peer()

    def _on_fullscreen_clicked(self, button: Gtk.Button) -> None:
        """Handle fullscreen toggle button."""
        window = self.get_root()
        if window:
            if window.is_fullscreen():
                window.unfullscreen()
            else:
                window.fullscreen()

    def _on_mouse_motion(self, controller, x, y) -> None:
        """Show fullscreen controls on mouse movement."""
        if self._state != DisplayState.RECEIVING:
            return

        self._controls_revealer.set_reveal_child(True)

        # Auto-hide after 3 seconds
        if self._fullscreen_controls_timeout:
            GLib.source_remove(self._fullscreen_controls_timeout)
        self._fullscreen_controls_timeout = GLib.timeout_add_seconds(3, self._hide_controls)

    def _hide_controls(self) -> bool:
        """Hide the fullscreen controls."""
        self._controls_revealer.set_reveal_child(False)
        self._fullscreen_controls_timeout = None
        return False  # Don't repeat

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle key presses (F11 for fullscreen, Escape to exit)."""
        from gi.repository import Gdk

        window = self.get_root()
        if not window:
            return False

        if keyval == Gdk.KEY_F11:
            if window.is_fullscreen():
                window.unfullscreen()
            else:
                window.fullscreen()
            return True
        elif keyval == Gdk.KEY_Escape:
            if window.is_fullscreen():
                window.unfullscreen()
                return True
        return False

    def _on_double_click(self, gesture, n_press, x, y) -> None:
        """Handle double-click for fullscreen toggle."""
        if n_press == 2:
            window = self.get_root()
            if window:
                if window.is_fullscreen():
                    window.unfullscreen()
                else:
                    window.fullscreen()

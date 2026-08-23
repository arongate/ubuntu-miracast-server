"""Main window for the Ubuntu Miracast Server."""

import logging
from enum import Enum

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from miracast_server import __version__

logger = logging.getLogger(__name__)


class Page(Enum):
    """Application page identifiers."""

    DISPLAY = "display"
    SESSIONS = "sessions"
    SETTINGS = "settings"


class MainWindow(Adw.ApplicationWindow):
    """Main application window for the Miracast Server.

    Contains a Gtk.Stack with three pages: Display, Sessions, Settings.
    Provides a header bar with status indicator and menu.
    """

    def __init__(self, application, advertiser, connection_handler, receiver, history, config):
        """Initialize the main window.

        Args:
            application: The Adw.Application instance.
            advertiser: MiracastAdvertiser instance.
            connection_handler: ConnectionHandler instance.
            receiver: MiracastReceiver instance.
            history: ServerSessionHistory instance.
            config: ServerConfig instance.
        """
        super().__init__(application=application)

        self.advertiser = advertiser
        self.connection_handler = connection_handler
        self.receiver = receiver
        self.history = history
        self.config = config

        self._setup_ui()
        self._connect_signals()
        logger.info("Main window initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        self.set_title("Ubuntu Miracast Server")
        self.set_default_size(900, 600)
        self.set_size_request(600, 400)

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        self._header = Adw.HeaderBar()
        main_box.append(self._header)

        # Status indicator in header
        self._status_label = Gtk.Label(label="Initializing...")
        self._status_label.add_css_class("dim-label")
        self._header.set_title_widget(self._status_label)

        # Menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_model = Gio.Menu()
        menu_model.append("Settings", "win.show-settings")
        menu_model.append("About", "win.show-about")
        menu_button.set_menu_model(menu_model)
        self._header.pack_end(menu_button)

        # Stack for page navigation
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        main_box.append(self._stack)

        # Create views (lazy imports to avoid circular deps)
        from miracast_server.ui.display_view import DisplayView
        from miracast_server.ui.sessions_view import SessionsView
        from miracast_server.ui.settings_view import SettingsView

        self._display_view = DisplayView(receiver=self.receiver)
        self._sessions_view = SessionsView(history=self.history)
        self._settings_view = SettingsView(config=self.config)

        self._stack.add_titled(self._display_view, Page.DISPLAY.value, "Display")
        self._stack.add_titled(self._sessions_view, Page.SESSIONS.value, "Sessions")
        self._stack.add_titled(self._settings_view, Page.SETTINGS.value, "Settings")

        # Bottom navigation bar
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bottom_bar.set_homogeneous(True)
        bottom_bar.add_css_class("toolbar")
        main_box.append(bottom_bar)

        for page_id, icon, label in [
            (Page.DISPLAY.value, "video-display-symbolic", "Display"),
            (Page.SESSIONS.value, "document-open-recent-symbolic", "Sessions"),
            (Page.SETTINGS.value, "preferences-system-symbolic", "Settings"),
        ]:
            btn = Gtk.Button()
            btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            btn_box.set_halign(Gtk.Align.CENTER)
            btn_box.append(Gtk.Image.new_from_icon_name(icon))
            btn_box.append(Gtk.Label(label=label))
            btn.set_child(btn_box)
            btn.connect("clicked", self._on_nav_clicked, page_id)
            bottom_bar.append(btn)

        # Set initial page
        self._stack.set_visible_child_name(Page.DISPLAY.value)

        # Register actions
        self._register_actions()

    def _register_actions(self) -> None:
        """Register window actions."""
        settings_action = Gio.SimpleAction.new("show-settings", None)
        settings_action.connect("activate", self._on_show_settings)
        self.add_action(settings_action)

        about_action = Gio.SimpleAction.new("show-about", None)
        about_action.connect("activate", self._on_show_about)
        self.add_action(about_action)

        # NFR-U03: Window-level key handler for reliable fullscreen exit
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_ctrl)

    def _connect_signals(self) -> None:
        """Connect GObject signals from core components."""
        self.advertiser.connect("advertising-started", self._on_advertising_started)
        self.advertiser.connect("advertising-stopped", self._on_advertising_stopped)
        self.advertiser.connect("advertising-error", self._on_advertising_error)

        self.connection_handler.connect("connection-received", self._on_connection_received)
        self.connection_handler.connect("connection-lost", self._on_connection_lost)
        self.connection_handler.connect("connection-error", self._on_connection_error)
        self.connection_handler.connect("pin-display", self._on_pin_display)

        self.receiver.connect("stream-started", self._on_stream_started)
        self.receiver.connect("stream-stopped", self._on_stream_stopped)
        self.receiver.connect("stream-error", self._on_stream_error)
        self.receiver.connect("stats-updated", self._on_stats_updated)

    def _on_nav_clicked(self, button: Gtk.Button, page_id: str) -> None:
        """Handle navigation button clicks."""
        self._stack.set_visible_child_name(page_id)

    def _on_show_settings(self, action, param) -> None:
        """Show settings page."""
        self._stack.set_visible_child_name(Page.SETTINGS.value)

    def _on_show_about(self, action, param) -> None:
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Ubuntu Miracast Server",
            application_icon="video-display",
            version=__version__,
            developer_name="Ubuntu Miracast Project",
            comments="Receive Miracast wireless display streams",
            license_type=Gtk.License.MIT_X11,
        )
        about.present()

    # ─── Signal handlers ──────────────────────────────────────────────

    def _on_window_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle window-level key presses for fullscreen control (NFR-U03)."""
        from gi.repository import Gdk

        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        elif keyval == Gdk.KEY_Escape:
            if self.is_fullscreen():
                self.unfullscreen()
                return True
        return False

    def _on_advertising_started(self, advertiser, group_interface: str) -> None:
        device_name = self.config.get("general", "device_name", "Ubuntu Miracast Server")
        self._status_label.set_text(f"Advertising as '{device_name}'")
        self._display_view.set_state_idle(device_name)

    def _on_advertising_stopped(self, advertiser) -> None:
        self._status_label.set_text("Advertising stopped")

    def _on_advertising_error(self, advertiser, error_msg: str) -> None:
        self._status_label.set_text(f"Error: {error_msg}")
        logger.error("Advertising error: %s", error_msg)

    def _on_connection_received(self, handler, connection) -> None:
        self._status_label.set_text(f"Connected: {connection.peer_name}")
        self._display_view.hide_pin()
        self._display_view.set_state_connected(connection.peer_name)

    def _on_connection_lost(self, handler) -> None:
        self._status_label.set_text("Connection lost")
        self._display_view.set_state_idle(
            self.config.get("general", "device_name", "Ubuntu Miracast Server")
        )

    def _on_connection_error(self, handler, error_msg: str) -> None:
        # Reset UI to idle/advertising state (PIN remains visible for retry)
        device_name = self.config.get("general", "device_name", "Ubuntu Miracast Server")
        self._status_label.set_text(f"Advertising as '{device_name}'")
        self._display_view.set_state_idle(device_name)
        logger.error("Connection error: %s", error_msg)

    def _on_pin_display(self, handler, pin: str, peer_addr: str) -> None:
        """Display PIN code persistently in the main display view."""
        self._status_label.set_text(f"PIN: {pin} — Waiting for source to connect")
        self._display_view.set_pin(pin)
        logger.info("Displaying PIN %s for peer %s", pin, peer_addr)

    def _on_pin_dialog_response(self, dialog, response: str) -> None:
        """Handle PIN dialog dismissal (legacy — no longer used)."""
        pass

    def _on_stream_started(self, receiver) -> None:
        self._status_label.set_text("Receiving stream")
        self._display_view.set_state_receiving()
        # Auto-fullscreen if configured
        if self.config.get("general", "fullscreen_on_stream", True):
            self.fullscreen()

    def _on_stream_stopped(self, receiver, stats) -> None:
        self._status_label.set_text("Stream ended")
        self._display_view.set_state_idle(
            self.config.get("general", "device_name", "Ubuntu Miracast Server")
        )
        if self.is_fullscreen():
            self.unfullscreen()

    def _on_stream_error(self, receiver, error_msg: str) -> None:
        self._status_label.set_text("Stream error")
        self._display_view.set_state_idle(
            self.config.get("general", "device_name", "Ubuntu Miracast Server")
        )
        if self.is_fullscreen():
            self.unfullscreen()
        logger.error("Stream error: %s", error_msg)

    def _on_stats_updated(self, receiver, stats: dict) -> None:
        self._display_view.update_stats(stats)

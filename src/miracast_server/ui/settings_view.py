"""Settings view for the Ubuntu Miracast Server.

Provides configuration UI with validation feedback for all server settings.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

logger = logging.getLogger(__name__)


class SettingsView(Gtk.ScrolledWindow):
    """Settings page with grouped configuration options.

    Groups: General, Streaming, Network, Service.
    Bound to ServerConfig for persistence with validation feedback.
    """

    def __init__(self, config):
        """Initialize the settings view.

        Args:
            config: ServerConfig instance.
        """
        super().__init__()
        self._config = config
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the settings UI with preference groups."""
        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        self.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        clamp.set_child(box)

        # ─── General Settings ─────────────────────────────────────────
        general_group = Adw.PreferencesGroup(title="General")
        box.append(general_group)

        # Device name
        self._device_name_row = Adw.EntryRow(title="Device Name")
        self._device_name_row.set_text(
            self._config.get("general", "device_name", "Ubuntu Miracast Server")
        )
        self._device_name_row.connect("changed", self._on_device_name_changed)
        general_group.add(self._device_name_row)

        # Start minimized
        self._start_minimized_row = Adw.SwitchRow(title="Start Minimized")
        self._start_minimized_row.set_active(
            self._config.get("general", "start_minimized", False)
        )
        self._start_minimized_row.connect("notify::active", self._on_switch_changed,
                                          "general", "start_minimized")
        general_group.add(self._start_minimized_row)

        # Fullscreen on stream
        self._fullscreen_row = Adw.SwitchRow(
            title="Fullscreen on Stream",
            subtitle="Automatically enter fullscreen when stream starts",
        )
        self._fullscreen_row.set_active(
            self._config.get("general", "fullscreen_on_stream", True)
        )
        self._fullscreen_row.connect("notify::active", self._on_switch_changed,
                                     "general", "fullscreen_on_stream")
        general_group.add(self._fullscreen_row)

        # Log level
        self._log_level_row = Adw.ComboRow(title="Log Level")
        log_levels = Gtk.StringList.new(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_row.set_model(log_levels)
        current_level = self._config.get("general", "log_level", "INFO")
        level_map = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        self._log_level_row.set_selected(level_map.get(current_level, 1))
        self._log_level_row.connect("notify::selected", self._on_log_level_changed)
        general_group.add(self._log_level_row)

        # ─── Streaming Settings ───────────────────────────────────────
        streaming_group = Adw.PreferencesGroup(title="Streaming")
        box.append(streaming_group)

        # RTSP port
        self._rtsp_port_row = Adw.EntryRow(title="RTSP Port")
        self._rtsp_port_row.set_text(
            str(self._config.get("streaming", "rtsp_port", 7236))
        )
        self._rtsp_port_row.connect("changed", self._on_rtsp_port_changed)
        streaming_group.add(self._rtsp_port_row)

        # Audio enabled
        self._audio_row = Adw.SwitchRow(title="Audio Enabled")
        self._audio_row.set_active(
            self._config.get("streaming", "audio_enabled", True)
        )
        self._audio_row.connect("notify::active", self._on_switch_changed,
                                "streaming", "audio_enabled")
        streaming_group.add(self._audio_row)

        # Max resolution
        self._resolution_row = Adw.ComboRow(title="Max Resolution")
        resolutions = Gtk.StringList.new(["1920x1080", "1280x720", "640x480"])
        self._resolution_row.set_model(resolutions)
        current_res = self._config.get("streaming", "max_resolution", "1920x1080")
        res_map = {"1920x1080": 0, "1280x720": 1, "640x480": 2}
        self._resolution_row.set_selected(res_map.get(current_res, 0))
        self._resolution_row.connect("notify::selected", self._on_resolution_changed)
        streaming_group.add(self._resolution_row)

        # Preferred codec
        self._codec_row = Adw.ComboRow(title="Preferred Codec")
        codecs = Gtk.StringList.new(["H264"])
        self._codec_row.set_model(codecs)
        self._codec_row.set_selected(0)
        streaming_group.add(self._codec_row)

        # ─── Network Settings ─────────────────────────────────────────
        network_group = Adw.PreferencesGroup(title="Network")
        box.append(network_group)

        # P2P Interface selector
        self._interface_row = Adw.ComboRow(
            title="P2P Interface",
            subtitle="Wi-Fi adapter to use for Miracast (empty = auto-detect)",
        )
        self._interface_list = Gtk.StringList.new(["(auto-detect)"])
        self._interface_values = [""]  # Corresponding values
        self._populate_interfaces()
        self._interface_row.set_model(self._interface_list)
        # Select current value
        current_iface = self._config.get("network", "p2p_interface", "")
        if current_iface and current_iface in self._interface_values:
            self._interface_row.set_selected(self._interface_values.index(current_iface))
        else:
            self._interface_row.set_selected(0)
        self._interface_row.connect("notify::selected", self._on_interface_changed)
        network_group.add(self._interface_row)

        # Refresh interfaces button
        refresh_row = Adw.ActionRow(title="Refresh Interfaces")
        refresh_row.set_subtitle("Rescan for available P2P Wi-Fi adapters")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.connect("clicked", self._on_refresh_interfaces)
        refresh_row.add_suffix(refresh_btn)
        refresh_row.set_activatable_widget(refresh_btn)
        network_group.add(refresh_row)

        # GO Intent
        self._go_intent_row = Adw.SpinRow.new_with_range(0, 15, 1)
        self._go_intent_row.set_title("GO Intent")
        self._go_intent_row.set_subtitle("Higher values prefer being Group Owner (0-15)")
        self._go_intent_row.set_value(
            self._config.get("network", "go_intent", 15)
        )
        self._go_intent_row.connect("notify::value", self._on_go_intent_changed)
        network_group.add(self._go_intent_row)

        # Connection timeout
        self._timeout_row = Adw.SpinRow.new_with_range(1, 120, 1)
        self._timeout_row.set_title("Connection Timeout")
        self._timeout_row.set_subtitle("Seconds to wait for P2P group formation (1-120)")
        self._timeout_row.set_value(
            self._config.get("network", "connection_timeout", 30)
        )
        self._timeout_row.connect("notify::value", self._on_timeout_changed)
        network_group.add(self._timeout_row)

        # Auto accept
        self._auto_accept_row = Adw.SwitchRow(
            title="Auto Accept Connections",
            subtitle="Automatically accept incoming Miracast connections",
        )
        self._auto_accept_row.set_active(
            self._config.get("network", "auto_accept", True)
        )
        self._auto_accept_row.connect("notify::active", self._on_switch_changed,
                                      "network", "auto_accept")
        network_group.add(self._auto_accept_row)

        # ─── Service Settings ─────────────────────────────────────────
        service_group = Adw.PreferencesGroup(title="Service Mode")
        box.append(service_group)

        # Service enabled
        self._service_row = Adw.SwitchRow(
            title="Enable Service Mode",
            subtitle="Run as a background systemd user service",
        )
        self._service_row.set_active(
            self._config.get("service", "enabled", False)
        )
        self._service_row.connect("notify::active", self._on_switch_changed,
                                  "service", "enabled")
        service_group.add(self._service_row)

        # Virtual display
        self._virtual_display_row = Adw.SwitchRow(
            title="Virtual Display",
            subtitle="Use a virtual display in service mode",
        )
        self._virtual_display_row.set_active(
            self._config.get("service", "virtual_display", False)
        )
        self._virtual_display_row.connect("notify::active", self._on_switch_changed,
                                          "service", "virtual_display")
        service_group.add(self._virtual_display_row)

        # Idle timeout
        self._idle_timeout_row = Adw.SpinRow.new_with_range(0, 86400, 60)
        self._idle_timeout_row.set_title("Idle Timeout")
        self._idle_timeout_row.set_subtitle("Seconds before service exits when idle (0 = disabled)")
        self._idle_timeout_row.set_value(
            self._config.get("service", "idle_timeout", 0)
        )
        self._idle_timeout_row.connect("notify::value", self._on_idle_timeout_changed)
        service_group.add(self._idle_timeout_row)

    # ─── Handlers ─────────────────────────────────────────────────────

    def _on_device_name_changed(self, row) -> None:
        """Handle device name change."""
        value = row.get_text().strip()
        if value:
            self._config.set("general", "device_name", value)

    def _on_switch_changed(self, row, pspec, section: str, key: str) -> None:
        """Handle switch toggle for boolean settings."""
        self._config.set(section, key, row.get_active())

    def _on_log_level_changed(self, row, pspec) -> None:
        """Handle log level selection change."""
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        idx = row.get_selected()
        if 0 <= idx < len(levels):
            self._config.set("general", "log_level", levels[idx])

    def _on_rtsp_port_changed(self, row) -> None:
        """Handle RTSP port change with validation."""
        text = row.get_text().strip()
        try:
            port = int(text)
            self._config.set("streaming", "rtsp_port", port)
            row.remove_css_class("error")
        except (ValueError, TypeError):
            row.add_css_class("error")

    def _on_resolution_changed(self, row, pspec) -> None:
        """Handle resolution selection change."""
        resolutions = ["1920x1080", "1280x720", "640x480"]
        idx = row.get_selected()
        if 0 <= idx < len(resolutions):
            self._config.set("streaming", "max_resolution", resolutions[idx])

    def _on_go_intent_changed(self, row, pspec) -> None:
        """Handle GO intent change."""
        try:
            self._config.set("network", "go_intent", int(row.get_value()))
        except ValueError:
            pass

    def _on_timeout_changed(self, row, pspec) -> None:
        """Handle connection timeout change."""
        try:
            self._config.set("network", "connection_timeout", int(row.get_value()))
        except ValueError:
            pass

    def _on_idle_timeout_changed(self, row, pspec) -> None:
        """Handle idle timeout change."""
        self._config.set("service", "idle_timeout", int(row.get_value()))

    def _populate_interfaces(self) -> None:
        """Populate the interface dropdown with available P2P interfaces."""
        from miracast_server.utils import list_p2p_interfaces

        interfaces = list_p2p_interfaces()
        for iface_info in interfaces:
            name = iface_info["interface"]
            parent = iface_info["parent"]
            driver = iface_info["driver"]
            label = f"{name} ({parent} — {driver})" if driver else f"{name} ({parent})"
            self._interface_list.append(label)
            self._interface_values.append(name)

    def _on_interface_changed(self, row, pspec) -> None:
        """Handle P2P interface selection change."""
        idx = row.get_selected()
        if 0 <= idx < len(self._interface_values):
            new_iface = self._interface_values[idx]
            self._config.set("network", "p2p_interface", new_iface)

            # Trigger runtime switch if the app is running
            window = self.get_root()
            if window:
                app = window.get_application()
                if app and hasattr(app, "switch_interface"):
                    app.switch_interface(new_iface)

    def _on_refresh_interfaces(self, button: Gtk.Button) -> None:
        """Refresh the interface list."""
        # Clear existing entries (keep the first "(auto-detect)" entry)
        while self._interface_list.get_n_items() > 1:
            self._interface_list.remove(self._interface_list.get_n_items() - 1)
        self._interface_values = [""]

        # Rebuild
        self._interface_list.splice(0, self._interface_list.get_n_items(), ["(auto-detect)"])
        self._interface_values = [""]
        self._populate_interfaces()

        # Re-select current value
        current_iface = self._config.get("network", "p2p_interface", "")
        if current_iface and current_iface in self._interface_values:
            self._interface_row.set_selected(self._interface_values.index(current_iface))
        else:
            self._interface_row.set_selected(0)

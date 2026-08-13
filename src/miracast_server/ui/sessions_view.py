"""Sessions history view for the Ubuntu Miracast Server.

Displays a list of past streaming sessions with details.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

logger = logging.getLogger(__name__)


class SessionsView(Gtk.Box):
    """View displaying past streaming session history.

    Shows session records with source name, date, duration, resolution,
    and data received. Provides a clear history button with confirmation.
    """

    def __init__(self, history):
        """Initialize the sessions view.

        Args:
            history: ServerSessionHistory instance.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._history = history
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        # Toolbar with title and clear button
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.set_margin_start(16)
        toolbar.set_margin_end(16)
        toolbar.set_margin_top(12)
        toolbar.set_margin_bottom(8)
        self.append(toolbar)

        title = Gtk.Label(label="Session History")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_xalign(0)
        toolbar.append(title)

        self._clear_btn = Gtk.Button(label="Clear History")
        self._clear_btn.add_css_class("destructive-action")
        self._clear_btn.connect("clicked", self._on_clear_clicked)
        toolbar.append(self._clear_btn)

        # Scrollable list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scrolled)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        self._list_box.set_margin_bottom(16)
        scrolled.set_child(self._list_box)

        # Placeholder for empty state
        self._placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._placeholder.set_valign(Gtk.Align.CENTER)
        placeholder_icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
        placeholder_icon.set_pixel_size(48)
        placeholder_icon.add_css_class("dim-label")
        self._placeholder.append(placeholder_icon)
        placeholder_label = Gtk.Label(label="No sessions yet")
        placeholder_label.add_css_class("dim-label")
        self._placeholder.append(placeholder_label)
        self._list_box.set_placeholder(self._placeholder)

    def refresh(self) -> None:
        """Refresh the session list from history."""
        # Clear existing rows
        while True:
            row = self._list_box.get_row_at_index(0)
            if row is None:
                break
            self._list_box.remove(row)

        # Add session rows
        sessions = self._history.get_sessions()
        for record in sessions:
            row = self._create_session_row(record)
            self._list_box.append(row)

        # Update clear button sensitivity
        self._clear_btn.set_sensitive(len(sessions) > 0)

    def _create_session_row(self, record) -> Gtk.ListBoxRow:
        """Create a list row for a session record."""
        row = Adw.ActionRow()

        # Title: source name
        row.set_title(record.source_info.name or "Unknown Source")

        # Subtitle: date + duration + resolution
        timestamp_str = record.timestamp.strftime("%Y-%m-%d %H:%M")
        duration_min = record.stats.duration // 60
        duration_sec = record.stats.duration % 60
        duration_str = f"{duration_min}m {duration_sec}s" if duration_min else f"{duration_sec}s"

        resolution = record.stats.resolution
        res_str = f"{resolution[0]}x{resolution[1]}" if resolution[0] > 0 else ""

        data_mb = record.stats.data_received / (1024 * 1024)
        data_str = f"{data_mb:.1f} MB"

        parts = [timestamp_str, duration_str]
        if res_str:
            parts.append(res_str)
        parts.append(data_str)

        row.set_subtitle(" · ".join(parts))

        # Icon
        row.add_prefix(Gtk.Image.new_from_icon_name("video-display-symbolic"))

        return row

    def _on_clear_clicked(self, button: Gtk.Button) -> None:
        """Handle clear history button with confirmation dialog."""
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Clear Session History?",
            body="This will permanently remove all session records. This action cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_clear_response)
        dialog.present()

    def _on_clear_response(self, dialog, response: str) -> None:
        """Handle the clear confirmation dialog response."""
        if response == "clear":
            self._history.clear()
            self.refresh()
            logger.info("Session history cleared by user")

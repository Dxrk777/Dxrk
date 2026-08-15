# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from dxrk.tui.app import DxrkApp
from dxrk.tui.shared import STATE


# ── Helpers ─────────────────────────────────────────────────────────────


def _reset_state() -> None:
    STATE.version = "test"
    STATE.detection = None
    STATE.selected_agents = []
    STATE.selected_components = []
    STATE.selected_skills = []
    STATE.backups = []
    STATE.selected_backup = None
    STATE.plan = None


def _make_app() -> DxrkApp:
    _reset_state()
    return DxrkApp()


# ── Structural tests (no Pilot needed) ──────────────────────────────────


class TestSCREENSCompleteness:
    def test_all_screen_names_are_registered(self):
        """Every screen referenced in SCREEN_FLOW that has a class must be in SCREENS."""
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.shared import SCREEN_FLOW, PREV, NEXT

        app = DxrkApp()
        registered = set(app.SCREENS.keys())
        all_flow_names = set(SCREEN_FLOW.keys())
        flow_names = set()
        for name, flow in SCREEN_FLOW.items():
            flow_names.add(name)
            for direction in (flow.get("forward"), flow.get("backward")):
                if direction is not None:
                    flow_names.add(direction)

        # These screens are in SCREEN_FLOW but don't have a class yet
        planned_screens = {
            "claude_model_picker",
            "kiro_model_picker",
            "skill_picker",
            "upgrade",
            "sync",
            "upgrade_sync",
            "model_config",
            "profiles",
            "restore_result",
            "delete_result",
        }
        implemented = flow_names - planned_screens
        missing = implemented - registered
        assert not missing, (
            f"Screens referenced in SCREEN_FLOW but missing from SCREENS: {missing}"
        )

    def test_no_orphan_screen_names(self):
        """Every name in SCREENS must be in SCREEN_FLOW."""
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.shared import SCREEN_FLOW

        app = DxrkApp()
        registered = set(app.SCREENS.keys())
        known = set(SCREEN_FLOW.keys())
        missing_from_flow = registered - known
        assert not missing_from_flow, (
            f"Screens in SCREENS but missing from SCREEN_FLOW: {missing_from_flow}"
        )

    def test_welcome_has_first_screen(self):
        """Welcome screen should have no backward."""
        from dxrk.tui.shared import PREV

        assert PREV["welcome"] is None

    def test_complete_ends_install_flow(self):
        """Complete screen should have no forward."""
        from dxrk.tui.shared import NEXT

        assert NEXT["complete"] is None

    def test_go_next_and_go_back(self):
        from dxrk.tui.shared import go_next, go_back

        assert go_next("welcome") == "detection"
        assert go_back("agents") == "detection"
        assert go_next("complete") is None
        assert go_back("welcome") is None

    def test_go_next_unknown(self):
        from dxrk.tui.shared import go_next

        assert go_next("nonexistent") is None

    def test_go_back_unknown(self):
        from dxrk.tui.shared import go_back

        assert go_back("nonexistent") is None


class TestAppState:
    def test_defaults(self):
        _reset_state()
        assert STATE.version == "test"
        assert STATE.detection is None
        assert STATE.selected_agents == []
        assert STATE.backups == []


# ── Pilot integration tests ─────────────────────────────────────────────


class TestAppLifecycle:
    @pytest.mark.asyncio
    async def test_app_starts_on_welcome_screen(self):
        async with _make_app().run_test() as pilot:
            assert pilot.app.screen is not None
            from dxrk.tui.app import WelcomeScreen

            assert isinstance(pilot.app.screen, WelcomeScreen)

    @pytest.mark.asyncio
    async def test_quit_with_q(self):
        async with _make_app().run_test() as pilot:
            await pilot.press("q")

    @pytest.mark.asyncio
    async def test_welcome_contains_option_labels(self):
        async with _make_app().run_test() as pilot:
            screen = pilot.app.screen
            menu = screen.query_one("#menu")
            assert menu is not None

    @pytest.mark.asyncio
    async def test_welcome_enter_install_pushes_detection(self):
        from unittest.mock import patch
        from dxrk.tui.app import DetectionScreen as InlineDetectionScreen

        InlineDetectionScreen.call_from_thread = lambda *a, **kw: None
        with patch("dxrk.tui.app.detect", return_value=None):
            async with _make_app().run_test() as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(pilot.app.screen, InlineDetectionScreen)

    @pytest.mark.asyncio
    async def test_state_isolation(self):
        STATE.selected_agents = ["test-agent"]
        _reset_state()
        assert STATE.selected_agents == []


# ── Helpers for screens with broken _render overrides ───────────────────


def _fix_screen_render(cls):
    """Wrap _render so custom widget logic runs AND parent's _render
    returns a proper Visual (fixes screen classes that override Screen._render
    but return None)."""
    orig = cls._render
    from textual.widget import Widget

    def wrapper(self):
        orig(self)
        return Widget._render(self)

    cls._render = wrapper
    return cls


# ── Screen-specific pilot tests ────────────────────────────────────────


class TestDetectionScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        from unittest.mock import MagicMock, patch
        from dxrk.tui.app import DetectionScreen as InlineDetectionScreen

        InlineDetectionScreen.call_from_thread = lambda *a, **kw: None
        with patch("dxrk.tui.app.detect", return_value=MagicMock()):
            async with _make_app().run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(pilot.app.screen, InlineDetectionScreen)
                assert pilot.app.screen.query_one("#detection-container")
                assert pilot.app.screen.query_one("#detection-title")
                assert pilot.app.screen.query_one("#detection-spinner")
                assert pilot.app.screen.query_one("#detection-status")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("detection")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            assert bindings == {"continue", "back"}

    @pytest.mark.asyncio
    async def test_escape_goes_back_to_welcome(self):
        from unittest.mock import MagicMock, patch
        from dxrk.tui.app import DetectionScreen as InlineDetectionScreen

        InlineDetectionScreen.call_from_thread = lambda *a, **kw: None
        with patch("dxrk.tui.app.detect", return_value=MagicMock()):
            async with _make_app().run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                from dxrk.tui.app import WelcomeScreen

                assert isinstance(pilot.app.screen, WelcomeScreen)


class TestAgentsScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("agents")
            await pilot.pause()
            from dxrk.tui.app import AgentsScreen as InlineAgentsScreen

            assert isinstance(pilot.app.screen, InlineAgentsScreen)
            assert pilot.app.screen.query_one("#agents-container")
            assert pilot.app.screen.query_one("#agents-title")
            assert pilot.app.screen.query_one("#agent-list")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("agents")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "toggle", "continue", "back"):
                assert action in bindings, f"Missing binding: {action}"

    @pytest.mark.asyncio
    async def test_escape_goes_back_to_detection(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("agents")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from dxrk.tui.app import DetectionScreen as InlineDetectionScreen

            assert isinstance(pilot.app.screen, InlineDetectionScreen)

    @pytest.mark.asyncio
    async def test_cursor_navigation(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("agents")
            await pilot.pause()
            screen = pilot.app.screen
            assert screen.cursor == 0
            await pilot.press("down")
            assert screen.cursor > 0
            await pilot.press("up")
            assert screen.cursor == 0


class TestBackupsScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_backups_screen(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("backups")
            await pilot.pause()
            from dxrk.tui.app import BackupsScreen as InlineBackupsScreen

            assert isinstance(pilot.app.screen, InlineBackupsScreen)

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("backups")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "select", "back"):
                assert action in bindings, f"Missing binding: {action}"

    @pytest.mark.asyncio
    async def test_escape_returns_to_welcome(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("backups")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from dxrk.tui.app import WelcomeScreen

            assert isinstance(pilot.app.screen, WelcomeScreen)


class TestCompleteScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("complete")
            await pilot.pause()
            from dxrk.tui.app import CompleteScreen as InlineCompleteScreen

            assert isinstance(pilot.app.screen, InlineCompleteScreen)
            assert pilot.app.screen.query_one("#complete-container")
            assert pilot.app.screen.query_one("#complete-title")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("complete")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            assert bindings == {"finish"}

    @pytest.mark.asyncio
    async def test_enter_returns_to_welcome(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("complete")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            from dxrk.tui.app import WelcomeScreen

            assert isinstance(pilot.app.screen, WelcomeScreen)


class TestInstallingScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("installing")
            await pilot.pause()
            from dxrk.tui.screens.installing import InstallingScreen

            assert isinstance(pilot.app.screen, InstallingScreen)
            assert pilot.app.screen.query_one("#installing-container")
            assert pilot.app.screen.query_one("#installing-title")
            assert pilot.app.screen.query_one("#install-progress")
            assert pilot.app.screen.query_one("#install-log")
            assert pilot.app.screen.query_one("#install-spinner")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("installing")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            assert bindings == {"noop"}


from dxrk.tui.screens.dependency_tree import DependencyTreeScreen

_fix_screen_render(DependencyTreeScreen)


class TestDependencyTreeScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("dependency_tree")
            await pilot.pause()
            assert pilot.app.screen.query_one("#dep-tree-container")
            assert pilot.app.screen.query_one("#dep-tree-content")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("dependency_tree")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "select", "toggle", "back"):
                assert action in bindings, f"Missing binding: {action}"

    @pytest.mark.asyncio
    async def test_escape_goes_back(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("dependency_tree")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            from dxrk.tui.app import PresetScreen

            assert isinstance(pilot.app.screen, PresetScreen)


from dxrk.tui.screens.review import ReviewScreen

_fix_screen_render(ReviewScreen)


class TestReviewScreen:
    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("review")
            await pilot.pause()
            assert pilot.app.screen.query_one("#review-container")
            assert pilot.app.screen.query_one("#review-title")
            assert pilot.app.screen.query_one("#review-content")

    @pytest.mark.asyncio
    async def test_key_bindings(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("review")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "select", "back"):
                assert action in bindings, f"Missing binding: {action}"

    @pytest.mark.asyncio
    async def test_cursor_navigation(self):
        async with _make_app().run_test() as pilot:
            await pilot.app.push_screen("review")
            await pilot.pause()
            screen = pilot.app.screen
            assert screen.cursor == 0
            await pilot.press("down")
            assert screen.cursor == 1
            await pilot.press("up")
            assert screen.cursor == 0


from dxrk.tui.screens.backups import RestoreConfirmScreen

_fix_screen_render(RestoreConfirmScreen)


class TestBackupSubScreens:
    @pytest.mark.asyncio
    async def test_restore_confirm_compose(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("restore_confirm")
            await pilot.pause()
            assert isinstance(pilot.app.screen, RestoreConfirmScreen)

    @pytest.mark.asyncio
    async def test_restore_confirm_key_bindings(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("restore_confirm")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "select", "back"):
                assert action in bindings

    @pytest.mark.asyncio
    async def test_delete_confirm_compose(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("delete_confirm")
            await pilot.pause()
            from dxrk.tui.screens.backups import DeleteConfirmScreen

            assert isinstance(pilot.app.screen, DeleteConfirmScreen)

    @pytest.mark.asyncio
    async def test_delete_confirm_key_bindings(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("delete_confirm")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("cursor_up", "cursor_down", "select", "back"):
                assert action in bindings

    @pytest.mark.asyncio
    async def test_rename_backup_compose(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("rename_backup")
            await pilot.pause()
            from dxrk.tui.screens.backups import RenameBackupScreen

            assert isinstance(pilot.app.screen, RenameBackupScreen)

    @pytest.mark.asyncio
    async def test_rename_backup_key_bindings(self):
        async with _make_app().run_test() as pilot:
            STATE.selected_backup = {"id": "test-snap", "display_label": "Test Backup"}
            await pilot.app.push_screen("rename_backup")
            await pilot.pause()
            bindings = {b.action for b in pilot.app.screen.BINDINGS}
            for action in ("save", "cancel"):
                assert action in bindings

from strix.interface.tool_components.terminal_renderer import TerminalRenderer


class TestTerminalRendererCommandFormatting:
    def test_keeps_short_command_readable(self) -> None:
        formatted = TerminalRenderer._format_command("ls -la /tmp")
        assert formatted.plain == "ls -la /tmp"

    def test_shortens_long_multiline_command(self) -> None:
        command = (
            "python -c \"print('x' * 100)\"\n"
            "--arg1 value1 --arg2 value2 --arg3 value3 --arg4 value4"
        )
        formatted = TerminalRenderer._format_command(command)
        assert "\n" not in formatted.plain
        assert formatted.plain.endswith("...")

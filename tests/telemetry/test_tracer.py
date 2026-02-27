from strix.telemetry.tracer import Tracer


class TestExecutedCommandsLog:
    def test_writes_command_text_to_global_executed_commands_log(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        tracer = Tracer("test-run")

        tracer.log_tool_execution_start(
            agent_id="agent-1",
            tool_name="terminal_execute",
            args={"command": "ls -la"},
        )

        commands_log = tmp_path / "strix_runs" / "logs" / "executed_commands.log"
        assert commands_log.exists()
        assert commands_log.read_text(encoding="utf-8") == "ls -la\n"

    def test_does_not_write_log_entry_when_command_missing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        tracer = Tracer("test-run")

        tracer.log_tool_execution_start(
            agent_id="agent-1",
            tool_name="terminal_execute",
            args={"timeout": 5},
        )

        commands_log = tmp_path / "strix_runs" / "logs" / "executed_commands.log"
        assert not commands_log.exists()

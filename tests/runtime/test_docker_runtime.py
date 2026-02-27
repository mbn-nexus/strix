from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from strix.runtime import SandboxInitializationError


@pytest.fixture
def mock_docker_client():
    with patch("strix.runtime.docker_runtime.docker") as mock_docker:
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        yield mock_client


@pytest.fixture
def runtime(mock_docker_client):
    from strix.runtime.docker_runtime import DockerRuntime

    return DockerRuntime()


class TestGetContainerIp:
    def test_returns_ip_from_bridge_network(self, runtime):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "bridge": {"IPAddress": "172.17.0.2"},
                }
            }
        }
        assert runtime._get_container_ip(container) == "172.17.0.2"

    def test_returns_ip_from_custom_network(self, runtime):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "my-network": {"IPAddress": "172.18.0.5"},
                }
            }
        }
        assert runtime._get_container_ip(container) == "172.18.0.5"

    def test_skips_empty_ip_and_uses_next(self, runtime):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "net1": {"IPAddress": ""},
                    "net2": {"IPAddress": "172.19.0.3"},
                }
            }
        }
        assert runtime._get_container_ip(container) == "172.19.0.3"

    def test_raises_when_no_networks(self, runtime):
        container = MagicMock()
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        with pytest.raises(SandboxInitializationError, match="Container IP not found"):
            runtime._get_container_ip(container)

    def test_raises_when_no_ip_address(self, runtime):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "bridge": {"IPAddress": ""},
                }
            }
        }
        with pytest.raises(SandboxInitializationError, match="Container IP not found"):
            runtime._get_container_ip(container)

    def test_raises_when_network_settings_missing(self, runtime):
        container = MagicMock()
        container.attrs = {}
        with pytest.raises(SandboxInitializationError, match="Container IP not found"):
            runtime._get_container_ip(container)

    def test_calls_reload_before_accessing_attrs(self, runtime):
        container = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "bridge": {"IPAddress": "172.17.0.2"},
                }
            }
        }
        runtime._get_container_ip(container)
        container.reload.assert_called_once()


class TestGetSandboxUrl:
    @pytest.mark.asyncio
    async def test_returns_url_with_container_name(self, runtime, mock_docker_client):
        container = MagicMock()
        container.name = "strix-scan-test"
        mock_docker_client.containers.get.return_value = container

        with patch.object(runtime, "_console_output") as mock_console_output:
            url = await runtime.get_sandbox_url("container-id-123", 5000)

        assert url == "http://strix-scan-test:5000"
        mock_console_output.assert_called_once_with(
            "Resolving sandbox URL for container container-id-123:5000"
        )

    @pytest.mark.asyncio
    async def test_raises_when_container_not_found(self, runtime, mock_docker_client):
        mock_docker_client.containers.get.side_effect = NotFound("not found")

        with pytest.raises(ValueError, match="Container .* not found"):
            await runtime.get_sandbox_url("missing-id", 48081)

    @pytest.mark.asyncio
    async def test_uses_internal_port(self, runtime, mock_docker_client):
        container = MagicMock()
        container.name = "strix-scan-test"
        mock_docker_client.containers.get.return_value = container

        url = await runtime.get_sandbox_url("container-id", 48080)
        assert url == "http://strix-scan-test:48080"


class TestRecoverContainerState:
    def test_recovers_token_only(self, runtime):
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": [
                    "PYTHONUNBUFFERED=1",
                    "TOOL_SERVER_TOKEN=my-secret-token",
                    "TOOL_SERVER_PORT=5000",
                ]
            },
        }
        runtime._recover_container_state(container)
        assert runtime._tool_server_token == "my-secret-token"  # noqa: S105

    def test_handles_missing_token(self, runtime):
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": [
                    "PYTHONUNBUFFERED=1",
                    "TOOL_SERVER_PORT=5000",
                ]
            },
        }
        runtime._recover_container_state(container)
        assert runtime._tool_server_token is None


class TestNoPortPublishing:
    def test_no_port_instance_variables(self, runtime):
        assert not hasattr(runtime, "_tool_server_port")
        assert not hasattr(runtime, "_caido_port")


class TestContainerResolutionOutput:
    def test_logs_when_creating_new_container(self, runtime, mock_docker_client):
        mock_docker_client.containers.get.side_effect = NotFound("not found")
        mock_docker_client.containers.list.return_value = []
        created_container = MagicMock()

        with (
            patch.object(runtime, "_create_container", return_value=created_container),
            patch.object(runtime, "_console_output") as mock_console_output,
        ):
            container = runtime._get_or_create_container("scan-123")

        assert container is created_container
        mock_console_output.assert_any_call("Resolving container for scan scan-123")
        mock_console_output.assert_any_call(
            "No reusable container found. Creating strix-scan-scan-123"
        )


class TestCreateContainerNetwork:
    def test_uses_current_container_network(self, runtime, mock_docker_client):
        current_container = MagicMock()
        current_container.attrs = {"NetworkSettings": {"Networks": {"strix-net": {}}}}

        created_container = MagicMock()
        mock_docker_client.containers.get.side_effect = [NotFound("not found"), current_container]
        mock_docker_client.containers.run.return_value = created_container

        with (
            patch("strix.runtime.docker_runtime.os.getenv", return_value="strix-main"),
            patch.object(runtime, "_wait_for_tool_server"),
        ):
            runtime._create_container("scan-123")

        run_kwargs = mock_docker_client.containers.run.call_args.kwargs
        assert run_kwargs["network"] == "strix-net"


class TestCreateSandbox:
    @pytest.mark.asyncio
    async def test_workspace_id_uses_container_name(self, runtime):
        container = MagicMock()
        container.id = "container-id-123"
        container.name = "strix-scan-test"

        runtime._tool_server_token = "test-token"  # noqa: S105

        with (
            patch.object(runtime, "_get_scan_id", return_value="scan-123"),
            patch.object(runtime, "_get_or_create_container", return_value=container),
            patch.object(runtime, "_register_agent"),
        ):
            sandbox_info = await runtime.create_sandbox("agent-123")

        assert sandbox_info["workspace_id"] == "strix-scan-test"

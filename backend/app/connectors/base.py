from abc import ABC, abstractmethod
from typing import Any


class JobHistoryConnector(ABC):
    """Read-only job history access. Implementations must not mutate customer pods."""

    @abstractmethod
    def fetch_runs(self, customer_key: str, environment: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class OracleDbConnector(ABC):
    """Read-only Oracle access for parameterized inspection templates only."""

    @abstractmethod
    def execute_template(
        self,
        sql_text: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
        row_limit: int,
        validate_only: bool = False,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class EssApiConnector(ABC):
    """Read-only ESS request/status access."""

    @abstractmethod
    def fetch_request_status(
        self, request_id: str | None = None, process_name: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError


class OciTelemetryConnector(ABC):
    """Read-only telemetry access."""

    @abstractmethod
    def fetch_metrics(self, selector: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class SqlObservationConnector(ABC):
    """Read-only SQL/plan/UDQ observation access."""

    @abstractmethod
    def fetch_observations(self, run_selector: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class VolumeSnapshotConnector(ABC):
    """Read-only business-volume metric access."""

    @abstractmethod
    def fetch_volume(self, run_selector: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class SlackConnector(ABC):
    @abstractmethod
    def send_alert(self, payload: dict[str, Any], destination: str | None = None) -> dict[str, Any]:
        raise NotImplementedError


class ConfluenceQueryCatalogConnector(ABC):
    @abstractmethod
    def fetch_templates(self, source_reference: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

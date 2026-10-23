"""Deployment: deploy file, isolated runs, secrets, and the kill switch.

``deploy`` packages an agent with its ``deploy.yaml`` and builds a minimal,
locked-down OCI image automatically. Each run executes in isolation; the
harness holds secrets so the model never sees raw keys.
"""

from __future__ import annotations

from wicklight.deploy.config import (
    EffectiveDeployment,
    SecretStatus,
    build_effective_deployment,
    render_effective_deployment,
)
from wicklight.deploy.errors import (
    DeployFileIssue,
    DeployFileValidationError,
    check_deploy_path,
    parse_and_validate_deploy,
)
from wicklight.deploy.parser import DeployFile, DeployFileError, parse_deploy_file
from wicklight.deploy.schema import (
    DeployConfig,
    Egress,
    SecretSource,
    SecretSpec,
    TriggerSpec,
    WebhookConfig,
)

__all__ = [
    "DeployConfig",
    "DeployFile",
    "DeployFileError",
    "DeployFileIssue",
    "DeployFileValidationError",
    "EffectiveDeployment",
    "Egress",
    "SecretSource",
    "SecretSpec",
    "SecretStatus",
    "TriggerSpec",
    "WebhookConfig",
    "build_effective_deployment",
    "check_deploy_path",
    "parse_and_validate_deploy",
    "parse_deploy_file",
    "render_effective_deployment",
]

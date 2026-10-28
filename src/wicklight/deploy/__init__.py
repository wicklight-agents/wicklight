"""Deployment: deploy file, isolated runs, secrets, and the kill switch.

``deploy`` packages an agent with its ``deploy.yaml`` and builds a minimal,
locked-down OCI image automatically. Each run executes in isolation; the
harness holds secrets so the model never sees raw keys.
"""

from __future__ import annotations

from wicklight.deploy.build import (
    BuildError,
    BuildResult,
    build_deployment,
    generate_containerfile,
    image_tag,
)
from wicklight.deploy.config import (
    EffectiveDeployment,
    SecretStatus,
    build_effective_deployment,
    render_effective_deployment,
)
from wicklight.deploy.dockerfile import render_containerfile
from wicklight.deploy.engine import EngineError, detect_engine
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
from wicklight.deploy.secrets import (
    MissingSecretsError,
    SecretResolutionError,
    resolve_secrets,
    secrets_for_tool,
)

__all__ = [
    "BuildError",
    "BuildResult",
    "DeployConfig",
    "DeployFile",
    "DeployFileError",
    "DeployFileIssue",
    "DeployFileValidationError",
    "EffectiveDeployment",
    "Egress",
    "EngineError",
    "MissingSecretsError",
    "SecretResolutionError",
    "SecretSource",
    "SecretSpec",
    "SecretStatus",
    "TriggerSpec",
    "WebhookConfig",
    "build_deployment",
    "build_effective_deployment",
    "check_deploy_path",
    "detect_engine",
    "generate_containerfile",
    "image_tag",
    "parse_and_validate_deploy",
    "parse_deploy_file",
    "render_containerfile",
    "render_effective_deployment",
    "resolve_secrets",
    "secrets_for_tool",
]

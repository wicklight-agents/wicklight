"""Deployment: deploy file, isolated runs, secrets, and the kill switch.

``deploy`` packages an agent with its ``deploy.yaml`` and builds a minimal,
locked-down OCI image automatically. Each run executes in isolation; the
harness holds secrets so the model never sees raw keys.
"""

from __future__ import annotations

from wicklight.deploy.approvals import (
    FileApprover,
    PendingApproval,
    pending_approvals,
    resolve_approval,
)
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
from wicklight.deploy.egress import (
    AllowedHost,
    allowlist_hosts,
    derive_allowlist,
    host_allowed,
)
from wicklight.deploy.engine import EngineError, detect_engine
from wicklight.deploy.errors import (
    DeployFileIssue,
    DeployFileValidationError,
    check_deploy_path,
    parse_and_validate_deploy,
)
from wicklight.deploy.host import Deployment, HostError
from wicklight.deploy.parser import DeployFile, DeployFileError, parse_deploy_file
from wicklight.deploy.proxy import (
    DeniedConnection,
    EgressProxy,
    trace_deny_writer,
)
from wicklight.deploy.schedule import cron_matches, next_fire
from wicklight.deploy.schema import (
    DeployConfig,
    Egress,
    OverlapPolicy,
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
from wicklight.deploy.supervisor import Supervisor, record_killed

__all__ = [
    "AllowedHost",
    "BuildError",
    "BuildResult",
    "DeniedConnection",
    "DeployConfig",
    "DeployFile",
    "DeployFileError",
    "DeployFileIssue",
    "DeployFileValidationError",
    "Deployment",
    "EffectiveDeployment",
    "Egress",
    "EgressProxy",
    "EngineError",
    "FileApprover",
    "HostError",
    "MissingSecretsError",
    "OverlapPolicy",
    "PendingApproval",
    "SecretResolutionError",
    "SecretSource",
    "SecretSpec",
    "SecretStatus",
    "Supervisor",
    "TriggerSpec",
    "WebhookConfig",
    "allowlist_hosts",
    "build_deployment",
    "build_effective_deployment",
    "check_deploy_path",
    "cron_matches",
    "derive_allowlist",
    "detect_engine",
    "generate_containerfile",
    "host_allowed",
    "image_tag",
    "next_fire",
    "parse_and_validate_deploy",
    "parse_deploy_file",
    "pending_approvals",
    "record_killed",
    "render_containerfile",
    "render_effective_deployment",
    "resolve_approval",
    "resolve_secrets",
    "secrets_for_tool",
    "trace_deny_writer",
]

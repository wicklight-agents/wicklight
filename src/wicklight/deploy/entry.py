"""Entrypoint for a deployed agent, run inside the container.

Resolves the deploy file's secrets from the runtime environment (injected by the
host, never baked into the image), failing fast and naming any that are missing.
The harness then holds the secrets and hands each tool only what it declared.

Triggers (schedule, webhook, manual) drive the actual runs; that wiring lands in
a later milestone. For now this confirms the deployment is sealed and ready, and
runs a single task when one is provided via ``WICKLIGHT_TASK``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from wicklight.deploy.errors import parse_and_validate_deploy
from wicklight.deploy.secrets import (
    MissingSecretsError,
    SecretResolutionError,
    resolve_secrets,
)


def main() -> int:
    deploy_path = Path(os.environ.get("WICKLIGHT_DEPLOY", "/app/deploy.yaml"))
    try:
        text = deploy_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"wicklight: cannot read {deploy_path}: {exc}", file=sys.stderr)
        return 1

    _file, config = parse_and_validate_deploy(text, filename=deploy_path.name)

    try:
        secrets = resolve_secrets(config, base_dir=deploy_path.parent, env=os.environ)
    except (MissingSecretsError, SecretResolutionError) as exc:
        print(f"wicklight: {exc}", file=sys.stderr)
        return 1

    task = os.environ.get("WICKLIGHT_TASK")
    if task is None:
        # No task yet: triggers will start runs. Report readiness without
        # revealing anything about the secret values.
        print(
            f"wicklight: ready — agent {config.name!r}, "
            f"{len(secrets)} secret(s) resolved, awaiting a trigger"
        )
        return 0

    from wicklight.agent import Agent

    agent_path = Path(os.environ.get("WICKLIGHT_AGENT", "/app/agent.md"))
    result = Agent.load(agent_path).run(task, secrets=secrets, runs_dir=config.traces)
    print(f"wicklight: run {result.run_id} {result.status.value}")
    return 0 if result.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())

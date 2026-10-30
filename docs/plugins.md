# Contracts and plugins

Wicklight owns a few small, versioned **contracts**; everything else is a
plugin. Providers, tools, and policies are discovered through Python entry
points, so a third party can extend Wicklight using only the public contract and
`wicklight.testing` — no imports from Wicklight internals. Each contract ships a
**conformance kit** so a plugin can prove it behaves before you depend on it.

| Plugin | Entry-point group | Implements | Conformance |
| --- | --- | --- | --- |
| Provider | `wicklight.providers` | `Provider` protocol | `run_provider_conformance` |
| Tool | `wicklight.tools` | `Tool` protocol | `run_tool_conformance` |
| Policy | `wicklight.policies` | a policy class | `run_policy_conformance` |

Register a plugin in your package's `pyproject.toml`:

```toml
[project.entry-points."wicklight.providers"]
my-llm = "my_package.provider:MyProvider"
```

Installed plugins appear in `wicklight providers list` (and are resolved by
`provider/model` id at run time).

## Writing a provider

A provider translates Wicklight's neutral request/response types to and from a
model API. It declares its contract version and capabilities, and implements
`complete` (and optionally `stream`):

```python
from wicklight.contracts import (
    Capabilities,
    ModelRequest,
    ModelResponse,
    StopReason,
    Usage,
)


class MyProvider:
    contract_version = "1.0"
    capabilities = Capabilities(tool_calls=True, streaming=False)

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def complete(self, request: ModelRequest) -> ModelResponse:
        ...  # call the API, map the result to a ModelResponse
        return ModelResponse(content="hi", stop_reason=StopReason.STOP, usage=Usage())
```

Keys come from the environment, never the agent file, and must never reach a
trace (Wicklight redacts known key shapes; see [credentials](credentials.md)).
Map provider errors to the neutral `ProviderError` kinds so the core's retries
and fallback work.

## Writing a tool

A tool is a named action with a typed input schema and a declared risk level.
The simplest form is an async function with the `@tool` decorator:

```python
from pydantic import BaseModel
from wicklight.contracts import ToolContext, ToolResult, ToolRisk, tool


class LookupInput(BaseModel):
    ticket_id: str


@tool(
    risk=ToolRisk.READ,
    network_hosts=["api.tracker.example"],
    sensitive=False,
    required_secrets=["TRACKER_TOKEN"],
)
async def lookup_ticket(inp: LookupInput, ctx: ToolContext) -> ToolResult:
    """Look up a support ticket."""
    token = ctx.secret("TRACKER_TOKEN")  # only secrets the tool declared
    ...
    return ToolResult.success("...")
```

`risk`, `network_hosts`, and `sensitive` are required declarations so the author
makes a conscious choice. `network_hosts` feeds the deployment
[egress allowlist](deploying.md); `required_secrets` limits which secrets the
tool is handed; errors are returned as a failed `ToolResult`, never raised.

## Writing a policy

A policy is a pure allow/deny check over a proposed tool call. It declares a
config model (validated from the agent file) and a `check` method:

```python
from wicklight.contracts.policy import ALLOW, PolicyCall, PolicyContext, deny


class BusinessHoursOnly:
    name = "business_hours_only"
    config_model = BusinessHoursConfig

    def __init__(self, config: BusinessHoursConfig) -> None:
        self._config = config

    def check(self, call: PolicyCall, ctx: PolicyContext):
        if _out_of_hours():
            return deny(f"{call.tool} is only allowed during business hours")
        return ALLOW
```

A policy must be deterministic, must not mutate anything, must be fast, and must
return a reason on deny (the trace cites it). It runs against *every* proposed
call, so allow anything it does not recognise.

## Running the conformance kit

Each kit exercises the contract's required behaviours and reports pass/fail.
From Python:

```python
import asyncio
from wicklight.testing import run_policy_conformance
from wicklight.contracts import PolicyRegistry, PolicyCall

factory = PolicyRegistry.discover().get("email_only_to")
report = run_policy_conformance(
    factory,
    config={"allow": ["@acme.com"]},
    sample_call=PolicyCall(tool="send_email", arguments={"to": "a@acme.com"}),
    deny_call=PolicyCall(tool="send_email", arguments={"to": "x@evil.com"}),
)
print(report.passed(), report.summary())
```

Provider authors can also run the kit as a pytest marker against an installed
provider:

```bash
pytest --wicklight-provider=my-llm -m conformance
```

Your plugin's own CI should install `wicklight` from PyPI and run the kit, so a
contract change is caught before it reaches users.

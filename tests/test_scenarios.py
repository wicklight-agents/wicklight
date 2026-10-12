"""The first safety scenarios, expressed with the scenario helper (DTN-215)."""

from __future__ import annotations

from wicklight.testing import Scenario

WORLD = "inbox:\n  - sender: amy@mycompany.com\n    subject: Hi\n"


def test_permitted_call_runs() -> None:
    scenario = Scenario(
        agent=(
            "---\nname: t\nmodels: { default: fake/x }\n"
            "tools:\n  read_inbox: read\n---\nSummarize the inbox.\n"
        ),
        script=(
            "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: done\n"
        ),
        world=WORLD,
    )
    scenario.run().assert_completed().assert_ran("read_inbox")


def test_over_permission_call_is_blocked() -> None:
    # send_email is a write tool but is only granted "read".
    scenario = Scenario(
        agent=(
            "---\nname: t\nmodels: { default: fake/x }\n"
            "tools:\n  send_email: read\n---\nReply to the inbox.\n"
        ),
        script=(
            "responses:\n  - tool_calls:\n      - name: send_email\n"
            '        arguments: { to: "x@y.com" }\n  - text: ok\n'
        ),
        world=WORLD,
    )
    result = scenario.run()
    result.assert_completed().assert_blocked(tool="send_email", by="permission")
    assert result.world.sent == []  # no email was sent


def test_runaway_script_hits_the_step_limit() -> None:
    scenario = Scenario(
        agent=(
            "---\nname: t\nmodels: { default: fake/x }\n"
            "tools:\n  read_inbox: read\nlimits: { max_steps: 2 }\n---\nLoop.\n"
        ),
        script="responses:\n" + "  - tool_calls:\n      - name: read_inbox\n" * 5,
        world=WORLD,
    )
    scenario.run().assert_stopped().assert_limit("max_steps")

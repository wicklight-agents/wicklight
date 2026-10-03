"""The three strict, versioned contracts and the harness's neutral types.

Provider, Tool, and Policy are the only extension points. Each has typed
inputs/outputs owned by the harness, a declared contract version and
capabilities checked at load time, and a conformance kit every plugin passes.
"""

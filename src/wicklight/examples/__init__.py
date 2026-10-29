"""Example tool plugins for the shipped example agents (DTN-258).

These make the example agents (``examples/inbox.md``, ``examples/payments.md``,
``examples/files.md``) runnable end to end — including inside a deployed
container, where tools are resolved through entry points rather than injected.
They reuse the :class:`~wicklight.tools.mock.MockWorld` data model but, unlike the
in-process test mocks, seed their world from a file (``WICKLIGHT_MOCK_WORLD``) in
the mounted volume and register as ``wicklight.tools`` plugins.

The world is loaded once per process and shared by every example tool, so state
(sent mail, the ledger) is consistent within a run. A long-lived supervisor
reuses that world across runs; for an isolated run, start a fresh process.
"""

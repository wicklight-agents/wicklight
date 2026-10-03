"""Deployment: deploy file, isolated runs, secrets, and the kill switch.

``deploy`` packages an agent with its ``deploy.yaml`` and builds a minimal,
locked-down OCI image automatically. Each run executes in isolation; the
harness holds secrets so the model never sees raw keys.
"""

# Examples

Example agent files live here. Each is an agent file with YAML frontmatter for
rules and a Markdown body for instructions, commented to teach one concept. All
of them pass `wicklight check`:

- [`inbox.md`](./inbox.md) — read an inbox and draft replies; send email only to
  a recipient allowlist, with approval.
- [`files.md`](./files.md) — read-only file access confined to a path allowlist.
- [`payments.md`](./payments.md) — an irreversible `make_payment` tool behind an
  approval gate, plus a spend cap.

```bash
uv run wicklight check examples/inbox.md
```

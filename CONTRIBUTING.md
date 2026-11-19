# Contributing

Keep changes focused, preserve GPL notices and add tests for protocol or cache
changes. Run `python -m unittest discover -s tests -v` in the installed virtual
environment. Document whether a result was tested with fixtures, a preview or
physical hardware; a mock/preview is not hardware acceptance.

Do not include local configuration, snapshots, private host addresses, keys,
tokens or unreviewed screenshots. Use synthetic fixtures. Never require a
privileged SSH account or weaken host verification to make a demo work.

Disclose AI assistance in the pull request, and use `Assisted-by: Briar` where
applicable rather than attributing AI assistance as human co-authorship.
Maintainers review and merge contributions; no automated merge is configured.

# New-session documentation verification

This runbook tests whether the repository can orient a fresh session without
the conversation that created it.

## Automated check

From a clean `familybot-core` checkout:

```bash
python3 scripts/validate_docs.py
```

The validator checks required handoff files, local Markdown links, balanced code
fences, canonical entry-point links and the single public family template.

## Cold-start reading drill

A new session reads only `AGENTS.md` and the files it directs. It must be able to
answer all of these questions with a file/path citation:

| Question | Expected destination |
| --- | --- |
| What is core and what is an add-on? | `docs/REPOSITORY_GUIDE.md` |
| Which failure behaviours may never regress? | `specs/RELIABILITY.md` |
| Where is household configuration defined? | `CONFIGURATION.md` and `config/family.example.json` |
| Where do tokens and passwords belong? | `CREDENTIALS.md` |
| How is the portal prevented from exposing raw family data? | `SECURITY.md` and portal `docs/DATA_BOUNDARY.md` |
| How should a Smart Home feature be added? | `specs/SMART_HOME.md` and `docs/CHANGE_PROTOCOL.md` |
| What must run before promotion? | `AGENTS.md` and `docs/CHANGE_PROTOCOL.md` |
| How is every bug fix, feature or improvement recorded? | `docs/CHANGE_PROTOCOL.md` |
| How can a failed deployment be restored? | `REDEPLOY.md` |

## Change-location drill

The documentation passes only if a new session chooses the right surface for
these examples:

1. A new subway station changes local config and is verified with
   `scripts/find_transport.py`; it does not require parser changes.
2. A misrouted `ukeplan` is core-critical and requires routing/parser fixtures,
   retry-state verification and the full core suite.
3. A vacuum integration is a Smart Home add-on behind Home Assistant; it must
   not modify email or delivery state.
4. A new child-facing card belongs in the portal and requires curated API,
   privacy and iPad acceptance review.
5. A new credential updates `CREDENTIALS.md`, remains outside Git and is tested
   by capability rather than output.

## Clean-archive drill

Use Git's tracked view so ignored runtime files cannot accidentally make the
documentation appear complete:

```bash
temporary_directory="$(mktemp -d)"
git archive HEAD | tar -x -C "$temporary_directory"
python3 "$temporary_directory/scripts/validate_docs.py" \
  --root "$temporary_directory"
```

Remove the temporary directory after inspection. The archive must contain the
agent contract, every linked local document and the validator, but no populated
family config, database, logs, attachments, PIN or credentials.

## Human verification record

For a documentation release, record in the commit or handoff:

- automated validator result;
- cold-start questions answered from tracked files;
- commands copied and checked against actual scripts/package entries;
- both repositories' dirty/branch state;
- whether runtime deployment was necessary.

Documentation-only releases require no service restart.

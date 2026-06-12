# Known MIB sources

Each `*.json` file in this directory declares one public MIB repository that the
SNMP module offers in the **MIB Manager → GitHub import** dropdown and as a
**compile dependency source**.  Files are auto-discovered at module import by
`_load_mib_sources()` in `../__init__.py` — **drop a new file here to add a
source; no code changes required.**

## File format

```json
{
    "order": 4,
    "name": "Vendor name",
    "folder": "https://github.com/owner/repo/tree/branch/path",
    "dep_templates": [
        "https://raw.githubusercontent.com/owner/repo/branch/path/@mib@.txt",
        "https://raw.githubusercontent.com/owner/repo/branch/path/@mib@"
    ]
}
```

| Field           | Required | Meaning                                                                                                   |
|-----------------|----------|-----------------------------------------------------------------------------------------------------------|
| `name`          | yes      | Label shown in the UI.                                                                                     |
| `folder`        | yes      | GitHub folder URL imported by the **Import folder** button (`.../tree/<branch>/<path>` or a bare repo).   |
| `dep_templates` | yes      | pysmi HTTP source templates; `@mib@` is replaced with the imported MIB module name during compilation.    |
| `order`         | no       | Sort key for the UI list (ascending). Files without it sort last, then alphabetically by `name`.          |

## Why a list of templates?

A single repository mixes file extensions (e.g. Net-SNMP stores MIBs as `.txt`,
`.mib` **and** extension-less; Cisco uses `.my`).  pysmi resolves an imported
module *by name*, so it must try every extension variant.  List one template per
extension the repo uses, plus a bare `@mib@` (no extension) entry — GitHub
returns a fast 404 for the variants that don't exist, so extra templates are
cheap.

## Validation

Malformed files (bad JSON, missing `name`/`folder`/`dep_templates`, or a
`folder` that isn't a recognised GitHub URL) are skipped with a log warning and
never break module import.

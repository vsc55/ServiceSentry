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
| `folder`        | one of   | GitHub folder URL imported by the **Import folder** button (`.../tree/<branch>/<path>` or a bare repo).   |
| `archive`       | one of   | URL of a ZIP the vendor publishes, imported by **Compare** / **Update**. See below.                       |
| `subdir`        | no       | Folder under `raw/` an archive unpacks into. Defaults to a slug of `name`.                                |
| `archive_only`  | no       | Folder INSIDE the archive that holds the MIBs. For a whole-repository zip: everything outside it is ignored, and the path itself is not kept — what is BELOW it is. |
| `dep_templates` | with `folder` | pysmi HTTP source templates; `@mib@` is replaced with the imported MIB module name during compilation. |
| `order`         | no       | Sort key for the UI list (ascending). Files without it sort last, then alphabetically by `name`.          |

## A repository zip instead of the API

GitHub's Contents API costs one request per FOLDER and allows sixty an hour without a token.
A repository with four hundred vendor folders — LibreNMS — cannot be walked on that, and the
import stops part way through with `rate limit exceeded`.

`codeload.github.com` serves the whole repository as one file and is **not** the API: no
allowance to spend. A source that publishes its MIBs inside a larger project declares that zip
as its `archive` plus the `archive_only` path its MIBs live under, and the import falls back to
it when GitHub refuses:

```json
{
    "name": "LibreNMS",
    "folder": "https://github.com/librenms/librenms/tree/master/mibs",
    "archive": "https://codeload.github.com/librenms/librenms/zip/refs/heads/master",
    "archive_only": "mibs",
    "subdir": "librenms"
}
```

Both routes stay. The API one is cheaper for anything it can actually do — one request lists a
folder, and the files themselves never touch the allowance — and the zip is a whole-repository
download to pick one folder out of (86 MB for LibreNMS, whose MIBs are 4830 files and 396 MB
uncompressed). Asked for a sub-folder of a declared source, the fallback keeps the sub-folder:
importing all of `mibs` when somebody asked for `mibs/synology` is four thousand files nobody
asked for.

## Folders and archives

A source is a **folder**, an **archive**, or both — projects that host MIBs publish a directory,
vendors publish one file, and the same vendor can be both (Synology is: its own ZIP, plus the
LibreNMS mirror as a dependency source for compilation).

An archive import **compares before writing**. Every MIB carries the `LAST-UPDATED` its author
wrote, and that is what says whether the archive is ahead of what is installed — a file's own
timestamp only says when it was downloaded. Each member comes back as `new`, `updated`,
`unchanged` or `older`; **Compare** reports all of it and writes nothing, and an `older` member
is skipped unless forced, because re-importing last year's archive over a MIB somebody fixed by
hand is a downgrade whose symptom turns up much later as an OID that stopped resolving.

Imported files keep the folder they came from, under `subdir`. The archive's own top-level
wrapper directory is dropped when every member shares it: it belongs to the packaging, not the
layout.

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

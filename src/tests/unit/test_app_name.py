#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The product's name lives in one place, and this is what keeps it there.

`lib.APP_NAME` is that place. Everything that SIGNS something with the name reads it from
there: the page titles, the sidebar head, the boot screen, the emails, the Teams cards, the
User-Agent, the diagnostics report. It used to be spelt out in fifty-odd string literals across
twenty-eight files, which is not a rename — it is a search, done by hand, where every hit has to
be judged.

Because judging them is the actual work, this guard does not simply ban the string. It bans it
where the panel is *signing itself*, and carries an explicit list of the two places that must
keep a literal, each with the reason:

* **identifiers registered in somebody else's system** — the Entra app display names and the
  Proxmox role and user. Those are looked up BY name in a tenant we do not own, so deriving them
  from `APP_NAME` would mean a rename quietly stops finding the app it registered last year and
  registers a second one beside it.
* **the repository URL** — GitHub's copy of the name, which a product rename does not move.

Translated prose (`lib/i18n/lang/*.py`) is out of scope by design: the name sits inside
sentences that have to be re-read in every language when it changes anyway.

Flask-free: it parses and reads files.
"""

import ast
import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
NAME = 'ServiceSentry'

# Files allowed to spell it out, and why. Anything else must read `APP_NAME` (Python),
# `{{ app_name }}` (a template) or `APP_NAME` (the JS constant in core/_constants.html).
ALLOWED_PY = {
    'lib/__init__.py':
        'the home — this is where the name is declared',
    'lib/config/spec.py':
        'the releases URL of the GitHub repository, which a product rename does not move',
    'lib/providers/entraid/declarations.py':
        'display names of apps registered in a customer tenant and looked up BY name; already '
        'a single source of truth of their own',
    'watchfuls/proxmox/provision.py':
        'the role and user created on the Proxmox node — identifiers in somebody else\'s system',
}

ALLOWED_HTML = {
    'lib/web_admin/templates/partials/cfg/notify/_msteams.html':
        'fallback for the Entra app display name injected from declarations.py',
    'lib/web_admin/templates/partials/credentials/_provision_wizard.html':
        'fallback text for a translation that has not loaded',
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _walk(root: str, ext: str, skip=('__pycache__', 'i18n', 'tests', '.venv')):
    for dirpath, dirnames, files in os.walk(os.path.join(SRC, root)):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for f in files:
            if f.endswith(ext):
                p = os.path.join(dirpath, f)
                yield os.path.relpath(p, SRC).replace(os.sep, '/'), p


def _docstring_nodes(tree) -> set:
    """Module/class/function docstrings — prose about the code, not code."""
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            out.add(id(body[0].value))
    return out


def _strip_html_comments(text: str) -> str:
    text = re.sub(r'\{#.*?#\}', '', text, flags=re.S)      # Jinja
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)     # HTML
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)      # JS block
    return re.sub(r'^\s*//.*$', '', text, flags=re.M)      # JS line


class TestTheNameHasOneHome:

    def test_the_constant_is_declared_where_the_version_is(self):
        """Above the submodule imports, like `__version__`: a module imported while the package
        is still initialising can still read it, which is what makes it safe to use from
        `config/spec.py` and everything else that loads early."""
        from lib import APP_NAME                                     # noqa: PLC0415
        assert APP_NAME and isinstance(APP_NAME, str)
        src = _read(os.path.join(SRC, 'lib', '__init__.py'))
        assert src.index('APP_NAME =') < src.index('from lib.'), \
            'declared after the submodule imports, so an early importer cannot read it'

    def test_the_pages_are_handed_it(self):
        """One context key, so no template has to know where the name comes from."""
        ctx = _read(os.path.join(SRC, 'lib', 'web_admin', 'mixins', 'context.py'))
        assert "'app_name': APP_NAME," in ctx
        consts = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                    '_constants.html'))
        assert 'const APP_NAME = {{ app_name | tojson }};' in consts, \
            'the JS half has no constant, so a script has to spell the name out'

    def test_the_brand_places_read_it(self):
        """The four the eye lands on: the tab, the head of the sidebar, the boot screen and the
        status page."""
        tpl = os.path.join(SRC, 'lib', 'web_admin', 'templates')
        for rel, needle in (
                ('base.html', '<title>{% block title %}{{ app_name }}{% endblock %}</title>'),
                (os.path.join('partials', '_sidebar.html'), '>{{ app_name }}</span>'),
                ('dashboard.html', '<div class="ss-boot-name">{{ app_name }}</div>'),
                (os.path.join('partials', '_status_body.html'),
                 '<h1 class="hero-title">{{ app_name }}</h1>')):
            assert needle in _read(os.path.join(tpl, rel)), rel

    def test_no_code_spells_it_out(self):
        """String LITERALS only — read with `ast`, so a comment or a docstring explaining the
        rule does not trip the guard that checks it."""
        bad = []
        for root in ('lib', 'watchfuls'):
            for rel, path in _walk(root, '.py'):
                if rel in ALLOWED_PY:
                    continue
                text = _read(path)
                if NAME not in text:
                    continue
                tree = ast.parse(text)
                skip = _docstring_nodes(tree)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                            and NAME in node.value and id(node) not in skip:
                        bad.append(f'{rel}:{node.lineno}')
        assert not bad, ('these spell the name instead of reading `APP_NAME` (or belong in '
                         'ALLOWED_PY with the reason): ' + ', '.join(sorted(set(bad))))

    def test_no_template_spells_it_out(self):
        """Comments stripped first — several of these files carry one that names the product
        while explaining something else entirely."""
        bad = []
        for root in ('lib', 'watchfuls'):
            for rel, path in _walk(root, '.html'):
                if rel in ALLOWED_HTML:
                    continue
                if NAME in _strip_html_comments(_read(path)):
                    bad.append(rel)
        assert not bad, ('these render the name instead of `{{ app_name }}` / the JS `APP_NAME` '
                         '(or belong in ALLOWED_HTML with the reason): ' + ', '.join(sorted(bad)))

    def test_the_exceptions_are_still_real(self):
        """An allow-list nobody prunes becomes the place the rule goes to die: each entry has to
        still contain the name, or it is a note about a file that moved on."""
        for rel in list(ALLOWED_PY) + list(ALLOWED_HTML):
            path = os.path.join(SRC, rel.replace('/', os.sep))
            assert os.path.isfile(path), f'{rel} is listed as an exception and does not exist'
            assert NAME in _read(path), f'{rel} no longer spells the name — drop the exception'

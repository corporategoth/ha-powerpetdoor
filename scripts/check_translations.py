#!/usr/bin/env python3
"""Audit translation coverage for the Power Pet Door integration.

Home Assistant already has a translation system, so this does not invent
one the way pypowerpetdoor's `t()` catalogue does. It audits HA's:

* `strings.json` is the **catalogue** - the authoritative set of keys and
  their English text.
* `translations/<lang>.json` are the **translations**.
* `translations/en.json` is a *copy* of `strings.json`. HA core generates it
  during its build; a custom integration has to ship it, so `--write-en`
  regenerates it rather than leaving a second place for English to drift.

Five questions, deliberately not conflated:

1. **Dangling** - code references a `translation_key` that `strings.json`
   does not define. This is the one that actually reaches a user: Home
   Assistant renders the raw key, so the dashboard shows
   `component.powerpetdoor.entity.switch.inside_sensor.name`. Always fatal.
2. **Orphaned** - a locale defines a key the catalogue no longer has. Dead
   weight being maintained for nothing. Fatal.
3. **Missing** - a locale has no entry for a catalogue key. Renders English.
   Reported, never fatal: a locale legitimately lags between a string
   landing and a translator reaching it.
4. **Placeholders** - `{name}` in the catalogue but not in the translation
   (or vice versa). HA raises at render time on a missing placeholder, so
   this is a crash, not a cosmetic issue. Fatal.
5. **Untranslated** - user-facing text that never entered the system at
   all: a hardcoded `_attr_name`, a bare-string `HomeAssistantError`, a
   literal in the Lovelace card. This is the one that measures coverage.

Usage:
    python scripts/check_translations.py [--untranslated] [--strict]
                                         [--write-en] [--locale de]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / "powerpetdoor"
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = COMPONENT / "translations"
CARD = REPO / "www" / "powerpetdoor-schedule-card.js"

#: Home Assistant looks entity names up at
#: `entity.<platform>.<translation_key>.name`, exception text at
#: `exceptions.<key>.message`, and so on. Code only ever names the leaf, so
#: resolving a `translation_key` to a catalogue path means trying each
#: section it could legally live under.
ENTITY_SECTIONS = (
    "binary_sensor",
    "button",
    "cover",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
    "time",
)

#: `{placeholder}` but not `{{escaped}}`.
_PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def flatten(data: object, prefix: str = "") -> dict[str, str]:
    """Nested translation JSON -> {"config.step.user.title": "..."}."""
    flat: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            flat.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(data, str):
        flat[prefix] = data
    return flat


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as error:
        sys.exit(f"{path}: invalid JSON - {error}")


def catalogue() -> dict[str, str]:
    return flatten(load_json(STRINGS))


def locales() -> dict[str, dict[str, str]]:
    """Every shipped translation, keyed by language code."""
    if not TRANSLATIONS.is_dir():
        return {}
    return {path.stem: flatten(load_json(path)) for path in sorted(TRANSLATIONS.glob("*.json"))}


# ---------------------------------------------------------------------------
# 1. Dangling references
# ---------------------------------------------------------------------------


def iter_python_files() -> list[Path]:
    return sorted(COMPONENT.rglob("*.py"))


def collect_references() -> dict[str, list[str]]:
    """Catalogue keys the Python code expects to exist -> where.

    Reads the AST rather than grepping, so a `translation_key` in a comment
    or a docstring is not mistaken for a real reference.
    """
    references: dict[str, list[str]] = {}

    def note(key: str, where: str) -> None:
        references.setdefault(key, []).append(where)

    for path in iter_python_files():
        rel = path.relative_to(REPO)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{rel}:{getattr(node, 'lineno', 0)}"

            # `_attr_translation_key = "inside_sensor"` and
            # `translation_key="inside_sensor"` in an EntityDescription.
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, "attr", None) or getattr(target, "id", None)
                    if (
                        name in ("_attr_translation_key", "translation_key")
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    ):
                        note(f"entity.*.{node.value.value}", where)

            if isinstance(node, ast.Call):
                keywords = {
                    kw.arg: kw.value
                    for kw in node.keywords
                    if kw.arg and isinstance(kw.value, ast.Constant)
                }
                key_node = keywords.get("translation_key")
                if key_node is None or not isinstance(key_node.value, str):
                    continue
                key = key_node.value
                func = node.func
                callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                # HomeAssistantError / ServiceValidationError / ConfigEntryNotReady
                # resolve under `exceptions.`; everything else is an entity
                # description.
                if callee.endswith(("Error", "NotReady", "AuthFailed")):
                    note(f"exceptions.{key}.message", where)
                else:
                    note(f"entity.*.{key}", where)
    return references


def resolve(key: str, keys: set[str]) -> bool:
    """Does a reference resolve against the catalogue?

    `entity.*.foo` is a wildcard: code names only the leaf, and the section
    is decided by which platform module the entity lives in.
    """
    if not key.startswith("entity.*."):
        return key in keys
    leaf = key.removeprefix("entity.*.")
    return any(f"entity.{section}.{leaf}.name" in keys for section in ENTITY_SECTIONS)


def check_dangling(keys: set[str]) -> list[str]:
    problems = []
    for key, wheres in sorted(collect_references().items()):
        if not resolve(key, keys):
            shown = key.replace("entity.*.", "entity.<platform>.")
            problems.append(
                f"{shown} referenced at {', '.join(wheres)} but strings.json has no such key"
            )
    return problems


# ---------------------------------------------------------------------------
# 2-4. Locale comparison
# ---------------------------------------------------------------------------


def compare(keys: dict[str, str], wanted: str | None) -> tuple[list[str], list[str], list[str]]:
    """(orphaned, missing, placeholder mismatches) across every locale."""
    orphaned: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []

    for language, entries in locales().items():
        if wanted and language != wanted:
            continue
        # en.json is a generated copy of strings.json; --write-en owns it and
        # comparing it to its own source would only ever restate that.
        if language == "en":
            if entries != keys:
                orphaned.append(
                    "translations/en.json has drifted from strings.json - re-run with --write-en"
                )
            continue

        for key in sorted(set(entries) - set(keys)):
            orphaned.append(f"{language}: {key} is not in strings.json")
        for key in sorted(set(keys) - set(entries)):
            missing.append(f"{language}: {key}")
        for key in sorted(set(keys) & set(entries)):
            expected = set(_PLACEHOLDER.findall(keys[key]))
            actual = set(_PLACEHOLDER.findall(entries[key]))
            if expected != actual:
                lost = ", ".join(sorted(expected - actual)) or "none"
                extra = ", ".join(sorted(actual - expected)) or "none"
                mismatched.append(
                    f"{language}: {key} placeholders differ (missing: {lost}; unexpected: {extra})"
                )
    return orphaned, missing, mismatched


# ---------------------------------------------------------------------------
# 5. Untranslated text
# ---------------------------------------------------------------------------


#: Text that reaches a person but never entered the translation system.
#: Each pattern below exists because it is a real way this integration has
#: leaked untranslated text, not because it is theoretically possible.
def find_untranslated() -> list[str]:
    found: list[str] = []

    for path in iter_python_files():
        rel = path.relative_to(REPO)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            line = getattr(node, "lineno", 0)

            # A hardcoded entity name. Platinum's has-entity-name rule wants
            # `_attr_translation_key`; an `_attr_name` string is text the
            # user sees in a language we never asked about.
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, "attr", None) or getattr(target, "id", None)
                    if (
                        name == "_attr_name"
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and node.value.value
                    ):
                        found.append(
                            f"{rel}:{line}: hardcoded _attr_name "
                            f"{node.value.value!r}; use _attr_translation_key"
                        )

            # An exception carrying a literal message instead of a
            # translation key. HA surfaces these verbatim in the UI.
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                call = node.exc
                callee = (
                    call.func.attr
                    if isinstance(call.func, ast.Attribute)
                    else getattr(call.func, "id", "")
                )
                if not callee.endswith(("Error", "NotReady")):
                    continue
                has_key = any(kw.arg == "translation_key" for kw in call.keywords)
                literal = call.args and isinstance(call.args[0], ast.Constant)
                if literal and not has_key and isinstance(call.args[0].value, str):
                    found.append(
                        f"{rel}:{line}: {callee} raised with a literal message; "
                        "pass translation_domain/translation_key"
                    )

    found.extend(find_untranslated_card())
    return found


#: A CSS declaration list - `display: flex; flex-direction: column;` or
#: `color: white; background: #03a9f4`. Prose almost never has this shape,
#: and inline styles are extremely common in this card.
_CSS_DECLARATIONS = re.compile(r"^\s*[a-z-]+\s*:\s*[^;:]+\s*(;\s*[a-z-]+\s*:\s*[^;:]+\s*)*;?\s*$")

#: A list of CSS class names or DOM ids - `slot-edge top`, `hour-line major`.
#: Every token is lowercase-hyphenated with no capitals and no punctuation.
#:
#: Capped at three tokens on purpose. Without the cap this also matched
#: lowercase *prose*, and silently swallowed the schedule summary line
#: ("N time slots across M days", which reduces to `time slot across day`
#: once its interpolations are blanked). Real class lists in this card are
#: one or two names; four lowercase words is a sentence.
_CLASS_LIST = re.compile(r"^[a-z][a-z0-9-]*( [a-z][a-z0-9-]*){0,2}$")

#: A run of HTML attributes - `tabindex="0" role="button" aria-label="..."`.
#: These reach the scanner as template text because the card builds them
#: conditionally inside an interpolation, but they are markup, not copy.
#: `? 'Foo' : 'Bar'` - a ternary picking between two string literals. Used to
#: catch user-facing words chosen inside a `${...}`, where the template
#: scanner deliberately blanks everything as code.
_TERNARY_LITERALS = re.compile(r"\?\s*['\"]([^'\"\\\n]{2,})['\"]\s*:\s*['\"]([^'\"\\\n]{2,})['\"]")

_ATTRIBUTE_SOUP = re.compile(r'^\s*[a-z-]+="[^"]*"(\s+[a-z-]+="[^"]*")*\s*$')

#: Single structural tokens: identifiers, WebSocket command types, URLs,
#: colours, `%c` format specifiers, times, pure punctuation/number soup.
_CARD_STRUCTURAL = re.compile(
    r"^[\s\d.:;%#/_-]*$"
    r"|^[a-z0-9_-]+$"
    r"|^[A-Za-z-]+/[A-Za-z0-9/_-]+$"
    r"|^(var\(|--|#[0-9a-fA-F]{3,8}$|rgba?\()"
    r"|^%c"
    r"|^\d{1,2}:\d{2}$"
)

#: Text that is genuinely user-facing but cannot be translated, with the
#: reason. Home Assistant's custom-card picker reads `window.customCards`
#: synchronously at script load, before any `hass` object exists, so there
#: is no localize() to call and no locale to call it with. Upstream has no
#: mechanism for this; these two strings are English by construction.
_CARD_UNTRANSLATABLE = {
    "Power Pet Door Schedule": "window.customCards name; read before hass exists",
    "A card to view and edit Power Pet Door schedules": (
        "window.customCards description; read before hass exists"
    ),
}


def _blank(text: str) -> str:
    """Same length, same newlines, no content - keeps line numbers honest."""
    return re.sub(r"[^\n]", " ", text)


def _blank_interpolations(source: str) -> str:
    """Blank `${ ... }` code inside template literals, keeping literal text.

    This is the subtle one, and the first version got it wrong in a way that
    silently disabled most of the audit.

    A `${cond ? 'a' : 'b'}` expression contains quote characters, so a naive
    scan for `'...'` reports the *fragment between* two unrelated quotes as
    a string - that is where entries like `" : h < 12 ? h + "` came from.
    Blanking the whole interpolation removes that.

    But interpolations NEST: this card renders as
    ``` `...${this._expanded ? `...prose...` : ''}...` ```
    and brace-matching over the outer `${` swallowed the inner template
    whole - taking the card's entire expanded body, and every user-facing
    string in it, out of the audit. The checker reported "all user-facing
    text is translated" while a hardcoded hint sat in plain sight.

    So this walks the two contexts properly and mutually recursively:
    inside a template, text is kept and `${` switches to code; inside code,
    everything is blanked except a nested template's text, which is kept.
    """
    out = list(source)
    length = len(source)
    #: (start, stop) of every template literal's own text, as walked. The
    #: caller cannot re-derive these with a regex: a naive `` `...` `` match
    #: pairs one template's closing backtick with the NEXT template's
    #: opening one and captures all the code in between, which is how a
    #: 2,000-character run of source came back reported as untranslated
    #: prose.
    spans: list[tuple[int, int]] = []

    def blank(start: int, stop: int) -> None:
        for position in range(start, min(stop, length)):
            if out[position] != "\n":
                out[position] = " "

    def scan_template(index: int) -> int:
        """Inside a template literal: keep text, recurse into `${`."""
        opened = index
        while index < length:
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char == "`":
                spans.append((opened, index))
                return index + 1
            if char == "$" and source[index + 1 : index + 2] == "{":
                index = scan_expression(index)
                continue
            index += 1
        return index

    def skip_quoted(index: int) -> int:
        """Step over a '...' or "..." string in CODE context.

        Without this a backtick inside an ordinary string opens a phantom
        template literal and every subsequent boundary is off by one, so the
        scanner reports whole runs of source as user-facing prose.
        """
        quote = source[index]
        index += 1
        while index < length:
            if source[index] == "\\":
                index += 2
                continue
            if source[index] == quote or source[index] == "\n":
                return index + 1
            index += 1
        return index

    def scan_expression(index: int) -> int:
        """Inside `${ ... }`: blank code, but keep nested template text."""
        pending = index
        depth = 0
        index += 1  # now at "{"
        while index < length:
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char in "\"'":
                index = skip_quoted(index)
                continue
            if char == "`":
                blank(pending, index + 1)
                index = scan_template(index + 1)
                pending = index
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    blank(pending, index + 1)
                    return index + 1
            index += 1
        blank(pending, index)
        return index

    index = 0
    while index < length:
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char in "\"'":
            index = skip_quoted(index)
            continue
        if char == "`":
            index = scan_template(index + 1)
            continue
        index += 1
    return "".join(out), spans


def _strip_js_noise(source: str) -> tuple[str, list[tuple[int, int]]]:
    """Remove comments and interpolations; report template text spans."""
    source = re.sub(r"/\*.*?\*/", lambda m: _blank(m.group(0)), source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", lambda m: _blank(m.group(0)), source)
    return _blank_interpolations(source)


#: Inside a template literal the card writes HTML. Tag markup is structural;
#: the text between tags, and a handful of attributes, are what a user reads.
_HTML_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_USER_FACING_ATTR = re.compile(
    r"\b(?:title|placeholder|aria-label|alt)\s*=\s*[\"']([^\"']{4,})[\"']"
)

#: The card carries its own catalogue - `const STRINGS = { en: { key: 'text' } }`
#: - because Home Assistant's translation machinery covers integrations, not
#: custom cards. Two consequences for this audit: the English strings inside
#: that object are the catalogue rather than "untranslated text", and a
#: `t(hass, 'key')` call naming a key it does not define renders the raw key
#: in the user's dashboard.
_CARD_CATALOGUE = re.compile(r"const STRINGS\s*=\s*\{(.*?)\n\};", re.DOTALL)
_CARD_ENTRY = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:\s*'((?:[^'\\]|\\.)*)'", re.MULTILINE)
_CARD_T_CALL = re.compile(r"\bt\(\s*[\w.]+\s*,\s*'([a-z_][a-z0-9_]*)'")

#: Text inside these elements is a label a user reads, however short. The
#: prose heuristic below needs two words, which is right for avoiding false
#: positives on identifiers - but it silently passed `<button>Delete</button>`
#: and `<label>From:</label>`, i.e. exactly the strings a translator most
#: needs. Inside these tags, one word is enough.
_LABEL_ELEMENT = re.compile(
    r"<(button|label|option|th|summary)\b[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE
)

#: `<style>` and `<script>` bodies are code, not copy. Their contents sit
#: *between* tags, so the tag-splitting pass below would otherwise hand the
#: card's entire stylesheet over as one enormous "untranslated string".
_EMBEDDED_CODE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)


def card_catalogue() -> tuple[dict[str, str], str]:
    """The card's own STRINGS table, and the source with it blanked out.

    Blanked rather than skipped so the reported line numbers of everything
    else stay correct.
    """
    if not CARD.exists():
        return {}, ""
    raw = CARD.read_text(encoding="utf-8")
    match = _CARD_CATALOGUE.search(raw)
    if match is None:
        return {}, raw
    entries = dict(_CARD_ENTRY.findall(match.group(1)))
    blanked = raw[: match.start()] + _blank(match.group(0)) + raw[match.end() :]
    return entries, blanked


def check_card_keys() -> list[str]:
    """`t()` calls whose key the card's catalogue does not define."""
    entries, source = card_catalogue()
    if not source:
        return []
    problems = []
    for match in _CARD_T_CALL.finditer(source):
        key = match.group(1)
        if key not in entries:
            line = source[: match.start()].count("\n") + 1
            problems.append(
                f"{CARD.relative_to(REPO)}:{line}: t(..., {key!r}) but STRINGS has no such key"
            )
    return problems


def find_untranslated_card() -> list[str]:
    """Prose baked into the Lovelace card.

    The card is plain browser JavaScript and this repo's toolchain has no JS
    parser, so this is a regex pass - deliberately conservative. It reports
    a literal only when it survives every structural filter *and* reads as
    prose (two or more alphabetic words, at least one containing a vowel).
    A false negative here is a missed translation; a false positive trains
    people to ignore the hook, which is worse.
    """
    if not CARD.exists():
        return []
    _entries, raw = card_catalogue()
    if not raw:
        return []
    source, template_spans = _strip_js_noise(raw)

    found: list[str] = []
    seen: set[str] = set()

    def consider(text: str, offset: int) -> None:
        # Blanked interpolations leave runs of spaces mid-sentence; collapse
        # them so the report shows "N time slots across M days" rather than
        # the ragged residue of `${count} time slot${...} across ${days}`.
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text in seen:
            return
        if text in _CARD_UNTRANSLATABLE or _CARD_STRUCTURAL.match(text):
            return
        if _CSS_DECLARATIONS.match(text) or _CLASS_LIST.match(text):
            return
        if _ATTRIBUTE_SOUP.match(text):
            return
        # Prose heuristic: two or more alphabetic words, and at least one
        # real word (a vowel) so identifier soup like "px solid" is skipped.
        words = [word for word in text.split() if word[:1].isalpha()]
        if len(words) < 2 or not any(set(word.lower()) & set("aeiou") for word in words):
            return
        seen.add(text)
        line = source[:offset].count("\n") + 1
        found.append(f"{CARD.relative_to(REPO)}:{line}: untranslated card text {text!r}")

    # Ordinary quoted strings, outside template literals.
    for match in re.finditer(r"'([^'\\\n]{4,})'|\"([^\"\\\n]{4,})\"", source):
        consider(match.group(1) or match.group(2), match.start())

    # Template literals: the card's HTML. Report the text between tags and
    # the attributes a user actually reads, not the markup. Spans come from
    # the scanner, which tracked nesting properly.
    for start, stop in template_spans:
        body = _EMBEDDED_CODE.sub(lambda m: _blank(m.group(0)), source[start:stop])
        base = start
        for attribute in _USER_FACING_ATTR.finditer(body):
            consider(attribute.group(1), base + attribute.start(1))
        # Short labels, before the prose filter can discard them.
        for element in _LABEL_ELEMENT.finditer(body):
            text = _HTML_TAG.sub(" ", element.group(2))
            text = re.sub(r"\s+", " ", text).strip()
            if not text or text in _CARD_UNTRANSLATABLE:
                continue
            if _CARD_STRUCTURAL.match(text) or not any(ch.isalpha() for ch in text):
                continue
            if text not in seen:
                seen.add(text)
                line = source[: base + element.start(2)].count("\n") + 1
                found.append(f"{CARD.relative_to(REPO)}:{line}: untranslated card label {text!r}")
        for chunk in _HTML_TAG.split(body):
            if chunk.strip():
                consider(chunk, base + body.find(chunk))

    # Prose chosen by a ternary INSIDE an interpolation, e.g.
    # `${isActive ? 'Active' : 'Inactive'}`. The scanner blanks interpolations
    # wholesale - they are code, and quoted strings there are usually keys or
    # CSS values - so text picked this way was invisible to every check above
    # and the card shipped two hardcoded English words with the gate green.
    #
    # Matched on the raw source, since the scanner has already blanked it.
    # Narrow on purpose: BOTH branches must be string literals, and one must
    # start with a capital letter, which is what separates prose from the
    # `'block'` / `'none'` / `'180deg'` the style blocks pick the same way.
    for match in _TERNARY_LITERALS.finditer(raw):
        for text in (match.group(1), match.group(2)):
            if text[:1].isupper() and text not in _CARD_UNTRANSLATABLE and text not in seen:
                seen.add(text)
                line = raw[: match.start()].count("\n") + 1
                found.append(
                    f"{CARD.relative_to(REPO)}:{line}: untranslated card text {text!r} "
                    f"(chosen by a ternary inside an interpolation)"
                )
    return found


# ---------------------------------------------------------------------------


def write_en(keys: dict[str, str]) -> bool:
    """Regenerate translations/en.json from strings.json. True if it moved."""
    TRANSLATIONS.mkdir(parents=True, exist_ok=True)
    target = TRANSLATIONS / "en.json"
    rendered = json.dumps(load_json(STRINGS), indent=2, ensure_ascii=False) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        print(f"  translations/en.json is current ({len(keys)} keys)")
        return False
    target.write_text(rendered, encoding="utf-8")
    print(f"  regenerated translations/en.json from strings.json ({len(keys)} keys)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", help="only audit this language code")
    parser.add_argument(
        "--untranslated", action="store_true", help="also report text outside the system"
    )
    parser.add_argument("--strict", action="store_true", help="also fail on missing translations")
    parser.add_argument(
        "--write-en",
        action="store_true",
        help="regenerate translations/en.json from strings.json",
    )
    args = parser.parse_args()

    if not STRINGS.exists():
        sys.exit(f"{STRINGS.relative_to(REPO)} does not exist")

    keys = catalogue()
    print(f"Catalogue: {len(keys)} keys in strings.json")
    card_keys, _ = card_catalogue()
    if card_keys:
        print(f"           {len(card_keys)} keys in the card's own STRINGS table")

    rewrote = False
    if args.write_en:
        print("\nGenerated English:")
        rewrote = write_en(keys)

    print("\nDangling references:")
    dangling = check_dangling(set(keys)) + check_card_keys()
    if dangling:
        for problem in dangling:
            print(f"  {problem}")
    else:
        print("  every translation_key in the code resolves")

    print("\nLocales:")
    orphaned, missing, mismatched = compare(keys, args.locale)
    for label, entries in (
        ("orphaned", orphaned),
        ("placeholder mismatch", mismatched),
        ("missing", missing),
    ):
        if entries:
            print(f"  {len(entries)} {label}:")
            for entry in entries[:20]:
                print(f"    {entry}")
            if len(entries) > 20:
                print(f"    ... and {len(entries) - 20} more")
    if not (orphaned or missing or mismatched):
        print("  every locale matches the catalogue")

    untranslated: list[str] = []
    if args.untranslated:
        print("\nUntranslated text:")
        untranslated = find_untranslated()
        if untranslated:
            print(f"  {len(untranslated)} string(s) outside the translation system:")
            for entry in untranslated[:30]:
                print(f"    {entry}")
            if len(untranslated) > 30:
                print(f"    ... and {len(untranslated) - 30} more")
        else:
            print("  all user-facing text is translated")

    print()
    fatal = len(dangling) + len(orphaned) + len(mismatched) + len(untranslated)
    if rewrote:
        print("FAIL: translations/en.json was regenerated; stage it and commit again")
        return 1
    if fatal:
        print(f"FAIL: {fatal} problem(s) that reach a user")
        return 1
    if missing and args.strict:
        print(f"FAIL (--strict): {len(missing)} missing translation(s)")
        return 1
    if missing:
        print(f"OK, with {len(missing)} missing translation(s) - locales may lag the source")
        return 0
    print("OK: translations are complete and consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())

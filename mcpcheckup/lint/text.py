"""Turning names and prose into something rules can compare.

Every rule that looks at text goes through this module, so that "what counts as a word"
is decided once. Two things follow from that:

* Rules stay short and readable, because the fiddly parts -- splitting `doStuff` into two
  tokens, deciding that `users` and `user` are the same idea -- happen here.
* The behaviour is testable on its own, which matters more than usual: a linter whose
  tokeniser is subtly wrong produces confident, specific, incorrect advice.

Nothing in here is clever. Crude, predictable, and offline beats accurate-but-occasionally
surprising for a tool that runs on every pull request. There is deliberately no stemmer, no
lemmatiser, no embedding model. Lint rules never call a model, and a dependency that had to
download one would break `uvx mcpcheckup` as an install-free command.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------------------
# Tokenising
# --------------------------------------------------------------------------------------

# Matches, in order: an acronym run not followed by a lowercase letter (HTTP in HTTPServer),
# a capitalised word (Server), a lowercase run, a digit run.
_IDENTIFIER_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")
_WORD = re.compile(r"[A-Za-z0-9]+")


def _vocab(words: str) -> frozenset[str]:
    """Build a vocabulary from a whitespace-separated block.

    A wrapper around `split()` so the word lists below can stay in the multi-line form,
    which is the only shape in which thirty words are readable and reviewable.
    """
    return frozenset(words.split())


# Words carrying no information about what a tool does. Removed before comparing prose so
# that two descriptions are not judged similar for both saying "the" a lot.
STOPWORDS: frozenset[str] = _vocab(
    """
    a an the this that these those there here it its is are was were be been being am
    of to in on for from by with at as into onto over under about against between
    and or but not no nor so if then than when where while which who whom whose what how
    you your yours they them their he she his her we our us i me my mine
    will would can could shall should may might must do does did done doing
    have has had having get gets got
    one two all any each every other another same more most some such only just also
    per via both either neither
    """
)

# Verbs that name an action without naming what it acts on. A tool called `get` or `run`
# tells a model nothing; the same verb in `get_user_profile` is fine.
BARE_VERBS: frozenset[str] = _vocab(
    """
    get set put post patch add read write list create make new update modify change edit
    delete remove destroy drop fetch find search query lookup send submit save store load
    run exec execute call invoke handle do perform process apply start stop begin end
    open close sync check test try use
    """
)

# Nouns that name a thing without saying which thing.
EMPTY_NOUNS: frozenset[str] = _vocab(
    """
    data stuff thing things item items info information object objects obj entry entries
    value values record records result results response responses request requests payload
    args arguments params parameters input inputs output outputs resource resources
    api tool tools func function functions method handler helper util utils
    action actions task tasks job jobs op ops operation operations command commands cmd
    misc temp tmp foo bar baz qux x y z
    """
)

# Tokens that carry no meaning on their own but are not verbs or nouns either.
FILLER_TOKENS: frozenset[str] = frozenset({"all", "the", "a", "an", "my", "our", "v", "v1", "v2"})

# Plurals that this crude singulariser would otherwise mangle. Consistency matters more
# than correctness here -- both sides of every comparison get the same treatment -- but a
# handful of guards keep the common cases sane.
_NEVER_SINGULAR: frozenset[str] = _vocab(
    """
    status address business access process analysis basis focus bonus census campus
    news series species alias index gas bus plus this its always perhaps
    """
)


def identifier_tokens(name: str) -> tuple[str, ...]:
    """Split a tool or parameter name into lowercase word tokens.

    Handles the three conventions that turn up in MCP servers, and mixtures of them:
    `search_users`, `searchUsers`, and `search-users` all yield `("search", "users")`.
    Digits break off on their own, which is what makes `ticket2` and `ticket` collide in
    the near-duplicate check.
    """
    return tuple(part.lower() for part in _IDENTIFIER_PART.findall(name))


def naming_style(name: str) -> str:
    """Classify a name's convention.

    A single all-lowercase word is `"flat"` rather than snake_case, because it is
    indistinguishable from camelCase and it would be wrong to accuse a server of mixing
    conventions on the strength of a name that conforms to both.
    """
    if "-" in name:
        return "kebab-case"
    if "_" in name:
        return "SCREAMING_SNAKE" if name.isupper() else "snake_case"
    if name[:1].isupper():
        return "PascalCase"
    if any(character.isupper() for character in name):
        return "camelCase"
    return "flat"


def singular(word: str) -> str:
    """A crude, deterministic singulariser -- enough to match `users` against `user`."""
    if word in _NEVER_SINGULAR or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")) and len(word) > 4:
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def all_words(text: str | None) -> tuple[str, ...]:
    """Every word in the text, lowercased -- stopwords included.

    This is what "the description is only three words long" counts, so it must not filter:
    a fragment made entirely of stopwords is still a fragment.
    """
    if not text:
        return ()
    return tuple(match.group().lower() for match in _WORD.finditer(text))


def content_words(text: str | None) -> tuple[str, ...]:
    """The meaningful words, singularised, in order and with duplicates kept.

    Duplicates survive because dropping them here would silently make every caller do set
    semantics; callers that want a set say so.
    """
    return tuple(
        singular(word)
        for word in all_words(text)
        if len(word) > 1 and word not in STOPWORDS and not word.isdigit()
    )


def content_bag(text: str | None) -> frozenset[str]:
    """`content_words` as a set, for similarity and subset comparisons."""
    return frozenset(content_words(text))


def meaningful_name_tokens(name: str) -> tuple[str, ...]:
    """Name tokens that say what the tool operates on: no verbs, fillers, or digits.

    `search_users` reduces to `("user",)`. That is the token a description has to justify,
    and dropping the verb is what stops a well-written description that says "Find people"
    from being accused of not mentioning "search".
    """
    return tuple(
        singular(token)
        for token in identifier_tokens(name)
        if not token.isdigit()
        and token not in BARE_VERBS
        and token not in EMPTY_NOUNS
        and token not in FILLER_TOKENS
        and len(token) > 1
    )


# --------------------------------------------------------------------------------------
# Comparing
# --------------------------------------------------------------------------------------


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Shared words over total distinct words. 0.0 when either side is empty.

    Chosen over TF-IDF cosine because it is *pairwise-local*: the score for two tools
    depends only on those two tools. A TF-IDF score is computed against the whole server,
    so adding an unrelated eleventh tool would silently move an existing pair's score and
    make a finding appear or vanish in CI for no reason the author changed. It is also the
    metric that explains itself -- "these two share 78% of their meaningful words" is a
    sentence a person can act on.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def token_appears(token: str, words: frozenset[str]) -> bool:
    """Whether a name token shows up in a bag of description words.

    Prefix matching in both directions, because the tokeniser is not a stemmer:
    `organization` should match `organizations`, and `comment` should match `commenting`.
    Restricted to tokens of four characters or more -- below that, prefix matching starts
    accepting coincidences like `org` inside `organic`.
    """
    if token in words:
        return True
    if len(token) < 4:
        return False
    return any(
        len(word) >= 4 and (word.startswith(token) or token.startswith(word)) for word in words
    )


def is_subset_of_name(text: str | None, name: str) -> bool:
    """Whether a description says nothing the name does not already say.

    True only when the text has content *and* every content word matches a name token, so
    an empty description falls to the missing-description rule rather than this one.
    """
    words = content_words(text)
    if not words:
        return False
    tokens = frozenset(singular(token) for token in identifier_tokens(name))
    return all(token_appears(word, tokens) for word in words)


# --------------------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------------------

# Characters per token, the rule of thumb for English prose and JSON under byte-pair
# encodings. Crude on purpose: a budget rule asks "is this too big to select reliably?",
# which does not need an exact count, and an exact count would mean a tokeniser dependency
# that downloads a model -- which lint must never have, because it runs on every pull
# request and has to work through install-free `uvx mcpcheckup`.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate how many tokens `text` costs a model, as characters over four.

    Rounds up, so any non-empty string costs at least one token. This is an estimate a
    budget is measured against, never presented as an exact figure -- the docs and the
    rule messages both say "about".
    """
    return -(-len(text) // _CHARS_PER_TOKEN)


# --------------------------------------------------------------------------------------
# Prose signals
# --------------------------------------------------------------------------------------

_TERMINAL_PUNCTUATION = frozenset(".!?")

# Text that says "I have not written this yet". Word boundaries keep `TBD` from matching
# inside a longer word; `lorem ipsum` and the rest are phrases people leave behind.
PLACEHOLDER_PATTERN = re.compile(
    r"""
    \b(?: TODO | FIXME | TBD | WIP | HACK | XXX+ | PLACEHOLDER | CHANGEME )\b
    | \blorem \s+ ipsum\b
    | \b(?: describe | document | fill \s+ in | add ) \s+ (?: this | me | here )\b
    | \b(?: no | missing | insert ) \s+ description\b
    | \bcoming \s+ soon\b
    | < (?: insert | your ) [^>]* >
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A description that tells a model when to prefer this tool over a similar one. Deliberately
# generous: the point is to reward authors who wrote *any* steering text, not to insist on
# a particular phrasing.
DISAMBIGUATION_PATTERN = re.compile(
    r"""
    \binstead\b | \brather \s+ than\b | \bunlike\b | \bas \s+ opposed \s+ to\b
    | \bprefer\b | \bin \s+ preference \s+ to\b
    | \buse \s+ this \s+ (?: when | only | for | to | if )\b
    | \bonly \s+ (?: when | use | if | for )\b
    | \bif \s+ you \s+ (?: need | want | have | are )\b
    | \b(?: do \s+ not | don't | never ) \s+ use \s+ this\b
    | \bnot \s+ for\b | \bcheaper\b | \bfaster \s+ than\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Concrete values a model can copy. `default` is deliberately absent: a default is what
# happens when nobody says anything, not a worked example of what a good value looks like.
EXAMPLE_PATTERN = re.compile(
    r"\be\.?\s?g\.?\s | \bfor \s+ example\b | \bfor \s+ instance\b | \bsuch \s+ as\b"
    r"| \blike \s+ ['\"`] | \bexamples?\s*:",
    re.IGNORECASE | re.VERBOSE,
)

# Prose that lists the allowed values of a parameter, e.g. "one of 'open', 'closed'".
ENUMERATION_PATTERN = re.compile(
    r"\bone \s+ of\b | \beither\b | \bmust \s+ be \s+ (?: one \s+ of | ['\"`] )"
    r"| \bvalid \s+ values\b | \ballowed \s+ values\b | \bpossible \s+ values\b",
    re.IGNORECASE | re.VERBOSE,
)


def has_terminal_punctuation(text: str | None) -> bool:
    return bool(text) and any(character in _TERMINAL_PUNCTUATION for character in text or "")


def mentions(text: str | None, name: str) -> bool:
    """Whether a description refers to another tool by name.

    Matches the name as written and as separate words, so a description that says
    "use `search_organizations`" and one that says "use search organizations" both count.
    """
    if not text:
        return False
    lowered = text.lower()
    if name.lower() in lowered:
        return True
    tokens = identifier_tokens(name)
    if len(tokens) < 2:
        return False
    return bool(re.search(r"\b" + r"[\s_-]+".join(re.escape(t) for t in tokens) + r"\b", lowered))


# --------------------------------------------------------------------------------------
# Domain vocabularies used by the schema and annotation rules
# --------------------------------------------------------------------------------------

# Parameter names that almost always denote a closed set of values.
ENUM_LIKE_NAMES: frozenset[str] = _vocab(
    """
    status state type kind mode level priority urgency severity importance
    format sort order direction ordering category visibility scope role permission
    environment env stage tier region locale language currency unit units
    strategy policy method operation frequency interval granularity resolution
    """
)

# Parameter names implying a value with a well-known syntax the schema should pin down.
DATE_LIKE_NAMES: frozenset[str] = _vocab(
    """
    date dates datetime timestamp time when since until before after
    deadline expiry expires
    """
)
# The Rails-style suffixes, which tokenise into pieces that mean nothing on their own.
DATE_LIKE_SUFFIXES: tuple[str, ...] = ("_at", "_date", "_time", "_on")
EMAIL_LIKE_NAMES: frozenset[str] = frozenset({"email", "emails", "mail", "recipient", "sender"})
URL_LIKE_NAMES: frozenset[str] = frozenset(
    {"url", "urls", "uri", "link", "links", "href", "endpoint", "webhook", "callback"}
)

# Vocabulary that marks a tool as doing something a user cannot take back.
DESTRUCTIVE_VERBS: frozenset[str] = _vocab(
    """
    delete remove destroy drop purge wipe erase truncate clear discard
    revoke terminate kill uninstall reset overwrite
    """
)
DESTRUCTIVE_PHRASE_PATTERN = re.compile(
    r"\bcannot \s+ be \s+ undone\b | \bcan't \s+ be \s+ undone\b | \bno \s+ undo\b"
    r"| \bpermanently\b | \birreversibl | \bunrecoverable\b | \bwithout \s+ recovery\b"
    r"| \bdestroys? \s+ (?: all | every )\b",
    re.IGNORECASE | re.VERBOSE,
)

# Verbs that mark a tool as a read. `check` and `export` are here because they turn up as
# read verbs far more often than not, and a wrong `readOnlyHint` is a warning, not an error.
READ_VERBS: frozenset[str] = _vocab(
    """
    get list search find read fetch query lookup show describe view browse
    count export download preview inspect check status
    """
)
READ_OPENING_PATTERN = re.compile(
    r"^\s*(?: returns? | retrieves? | reads? | lists? | finds? | searches | gets? | fetches"
    r"| looks \s+ up | shows? | queries | exports? | counts? )\b",
    re.IGNORECASE | re.VERBOSE,
)

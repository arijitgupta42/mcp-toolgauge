# How `eval` measures tool selection

`lint` reads your tools and tells you what looks wrong. `eval` puts those same tools in
front of a real model and counts what actually happens.

The two are answering different halves of the same question. Lint can say that two of your
descriptions share 78% of their meaningful words. Only eval can say that one of them is
therefore taking 62% of the other's traffic.

This page is the methodology. It exists because "we asked a model and it said so" is not a
measurement, and you should be able to tell the difference.

---

## What is being measured

One thing: **given a user's request and your tool list, does the model call the tool you
meant?**

Not whether the model's answer was good. Not whether the tool returned the right data --
`mcpcheckup` never calls your tools at all. Just selection, which is the step that fails
silently. A wrong tool call succeeds, returns plausible data, and nobody ever finds out.

The mechanics are deliberately ordinary, because the point is to reproduce what your users'
clients already do:

- your tools go to the model as real tool definitions -- your names, your descriptions,
  your JSON schemas, unedited
- `tool_choice` is `auto`, so *not* calling a tool is always available
- your server's `instructions` string, if it has one, goes into the system prompt, because
  a real client passes it along too
- temperature is 0, and is not configurable

Nothing is rewritten on the way through. A description that does not work here is a
description that does not work in production.

---

## The three kinds of case

A suite is not a pile of prompts. Each case has a *kind*, and the three are never averaged
together, because they measure different things.

| Kind | The question it asks |
|---|---|
| `positive` | Can this tool be found at all? |
| `sibling` | Can it be told apart from the tool it looks like? |
| `abstain` | Does the server know when to stay out of the way? |

**`sibling` cases are the ones that matter.** A suite made only of obvious prompts flatters
every server, including a bad one. So the pairs worth writing hard cases for are found
deliberately, using the same overlap measure the linter uses: the pairs `MCP013` and
`MCP014` complain about are exactly the pairs that get hard cases. That is the point where
the static and dynamic halves of this tool meet.

**`abstain` cases** exist because over-eager tool calling is a real failure that no
accuracy number catches. A server whose tools get called for everything is not doing well.

---

## The numbers

### Selection accuracy is the headline

```
selection accuracy = correct / total, over positive and sibling cases
```

Abstain cases are **excluded**. Argument validity is **excluded**. Both are reported
separately, on their own lines, and neither is ever folded in.

That is a deliberate choice, and the reason is simple: if abstention counted towards the
headline, you could raise your score by adding abstain cases to your own suite. That is a
change to the test, not to the server. The same reasoning keeps arguments out -- "a model
cannot tell your two search tools apart" and "your schema is hard to fill in" are different
defects with different fixes, and one number covering both points at neither.

The headline is also split by difficulty:

```
Selection accuracy   61%   35/57
  positives          78%   29/37
  siblings           30%    6/20
```

A server that is perfect on positives and a coin flip on siblings has a very specific
problem -- overlapping descriptions -- and it is not the same problem as a server that
cannot be found at all. One number would hide that.

### Abstention accuracy

How often the model correctly called nothing, over the `abstain` cases alone.

### Argument validity

Of every tool call the model made, how many were schema-valid. Counted against the schema
of the tool it *actually* called, not the one it should have -- the question is whether a
model can fill your schemas in, and that stands whichever tool it picked.

Four things are checked, each of which maps to a different fix:

| Reported as | Usually means |
|---|---|
| missing required parameter | the description never said where to get the value |
| undeclared parameter | a parameter name reads like something it is not |
| wrong type | the schema's type is not the one the name implies |
| value outside the enum | the allowed values were never written down |

This is not a full JSON Schema validator, on purpose. A general validator fails calls over
keywords that have nothing to do with whether the tool was usable, and its messages
("'x' is not valid under any of the given schemas") are not something you can act on.

### The confusion matrix

For every tool, where did the traffic meant for it actually go?

```
tool           hit       went instead to
search_orgs    17%  1/6  search_users 83%
doStuff        50%  1/2  (nothing) 50%
search_users   67%  4/6  search_orgs 33%
```

Shares are normalised **across the row** -- a cell is a fraction of the cases meant for
that tool. That is what makes the sentence underneath true as written:

```
search_users captures 83% of the prompts meant for search_orgs.
```

Normalising down the column instead would produce a number about the thief rather than
about the victim, and the victim is the one you have to go and fix.

A tool's row always sums to 1.0 regardless of what else is on the server, so adding an
unrelated eleventh tool cannot move an existing pair's number.

---

## What makes a run reproducible

**Cases are a committed artifact.** `--init` drafts a suite once. You edit it. Every run
after that reads it unchanged. Nothing regenerates it silently -- `--init` refuses to
overwrite an existing file without `--force` -- because a suite that quietly rewrote itself
would make two runs incomparable, which defeats the point of having a score.

**Every answer is cached**, keyed by `hash(model, prompt, tool digest)`. A second run of an
unchanged suite makes zero network calls and costs nothing. Commit the cache and CI can
replay the whole run offline, forever, for free.

**The tool digest is in the key.** Edit a description and the cached answers for it are
invalidated -- which is correct, because that edit is the thing you are trying to measure.
The digest is order-insensitive, so merely reshuffling your tool registrations does not
throw away a cache you paid for.

**Temperature is 0 and one sample is taken per case.** No `k`-sampling and no majority vote:
the cost multiplies, and the cache already makes a re-check free.

---

## What this does not tell you

Worth saying plainly, because a number invites more confidence than it earns.

- **One model's opinion.** A score is always reported with the model that produced it,
  because a score without one is not a score. Different models will disagree, sometimes
  substantially. Run more than one if the answer matters.
- **Your generated cases are only as good as your edits.** A drafted suite is a first
  draft. If the prompts do not sound like your users, the number is about somebody else's
  users. **Read the abstain cases first** -- they are the ones a generator gets wrong most
  often, because writing a request that sounds in-domain and is genuinely unanswerable is
  harder than it looks. A drafted "abstain" that one of your tools can actually answer is a
  positive case wearing the wrong label, and it will cost you a point every run for a
  server that did nothing wrong.
- **Small sample sizes are noisy.** Four cases per tool means one flipped answer moves a
  tool's rate by 25 points. Treat the confusion *pattern* as the signal and the second
  decimal place as noise.
- **It measures selection, not usefulness.** A tool can be selected perfectly and still be
  the wrong tool to have built.

---

## Reading a run

```bash
mcpcheckup eval ./your-server --init    # draft a suite; then edit it and commit it
mcpcheckup eval ./your-server           # run it
mcpcheckup eval ./your-server -v        # every failing case, with the prompt
mcpcheckup eval ./your-server --offline # replay the cache; no model, no cost
```

Start at the bottom. The sentences naming two tools are the finding; the percentages above
them are context for it. Then open the tool with the worst hit rate, read its description
next to whichever tool is taking its traffic, and ask what the first sentence of each says
that the other one does not.

That is usually the whole fix.

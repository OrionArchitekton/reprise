"""Demo prompts for the "try something new" control.

This lives on the server, not in the template, because only the server can see
what the library actually holds. The library is shared: a prompt one visitor
generates is spent for every visitor after them, so a pool that each browser
shuffles for itself cannot keep the promise the button makes. It only lowers
the odds of breaking it.

The prompts are deliberately far apart in meaning rather than variations on a
theme. The library matches on embedding similarity, not on text, so near
neighbours would land in the review band (0.85 to 0.97) instead of generating,
and a nonce appended to one prompt would score around 0.99 and auto-serve the
same asset.
"""

from __future__ import annotations

NOVEL_PROMPTS: tuple[str, ...] = (
    "a brass telescope on a wooden observatory floor, warm lamplight, film photograph",
    "a bowl of ramen with soft egg and scallions, overhead shot, food photography",
    "an origami crane folded from sheet music, macro, soft studio light",
    "a desert bus stop at noon, heat haze, kodachrome",
    "a kelp forest seen from below, sunbeams through water, wide angle",
    "a vinyl record spinning on a turntable, shallow depth of field, night",
    "a snow leopard on a rock ledge, overcast mountain light, wildlife photograph",
    "a stack of secondhand books beside a cold coffee, morning window light",
    "an empty subway platform at 2am, long exposure",
    "a hand painted fishing boat on a shingle beach, watercolor",
    "a greenhouse full of ferns after rain, condensation on the glass",
    "an espresso machine with steam and copper piping, industrial product shot",
    "a wheat field bending under a storm front, oil painting",
    "a chess endgame on a marble board, raking side light, still life",
    "a neon laundromat sign reflected in a wet street, cyberpunk illustration",
    "a hot air balloon over terraced rice fields at sunrise",
    "a violin workshop bench with wood shavings and hand tools, natural light",
    "a lynx track in fresh snow, close up, blue hour",
    "a paper map folded open on a car dashboard, road trip, 35mm",
    "a cathedral of ice inside a glacier, headlamp lighting",
)


def unseen_prompts(stored_prompts: list[str]) -> list[str]:
    """Pool entries the library does not already hold, in pool order.

    Exact text comparison on purpose: this is the same normalisation the exact
    match path uses, and it costs nothing. A pool entry that is merely SIMILAR
    to something stored still generates or goes to review, both of which are
    honest outcomes for the control. Only an exact repeat makes it a lie.
    """
    stored = {p.strip().lower() for p in stored_prompts}
    return [p for p in NOVEL_PROMPTS if p.strip().lower() not in stored]

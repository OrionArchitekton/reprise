"""The gateway: one entry point that answers "reuse, review, or generate?".

Flow per request:

1. Scan the library (a projection of the manifests in B2) and try the free
   path first: exact prompt match under hard constraints. No embedding call
   is spent on a request an exact match can answer.
2. Otherwise embed the request, score the substitutable candidates, and apply
   the acceptance policy (`classify`).
3. Act on the verdict:
   * REUSE    -- mint a short-lived serve URL for the stored asset. Nothing
                 is generated, nothing is spent.
   * REVIEW   -- return the ranked candidates for a human to decide.
   * GENERATE -- run a Genblaze pipeline (provider chosen by modality),
                 persist asset + provenance manifest through
                 ObjectStorageSink, and return the fresh entry.
4. Every verdict is recorded in the object-locked ledger BEFORE the response
   is returned; the scoreboard is derived from the ledger, never cached.

Deliberate non-goals at this scale: the library rescan per request is O(bucket
listing) and fine for a demo corpus; a production deployment would hold an
index (the ParquetSink tables are the natural seed for one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from genblaze_core import Manifest, Modality, ObjectStorageSink, Pipeline
from genblaze_core.providers.base import BaseProvider
from genblaze_core.storage.base import StorageBackend

from reprise.decide import decide
from reprise.embed import Embedder
from reprise.ingest import entries_from_manifest
from reprise.ledger import Ledger
from reprise.library import B2Library
from reprise.model import Decision, LibraryEntry, Request, Verdict
from reprise.nearmatch import classify, score_candidates

# How a modality gets generated: a provider factory plus the model id to ask
# for. A factory (not an instance) because providers own network clients and
# the pipeline closes what it is handed; each generate() gets a fresh one.
ProviderSpec = tuple[Callable[[], BaseProvider], str]


@dataclass(frozen=True, slots=True)
class GatewayResult:
    decision: Decision
    # Short-lived URL for the asset being served (REUSE) or just created
    # (GENERATE). None for REVIEW/errorless-GENERATE-only flows without serve.
    serve_url: str | None = None
    # The entry created by a GENERATE, so callers can show what was made.
    new_entry: LibraryEntry | None = None


class Gateway:
    def __init__(
        self,
        backend: StorageBackend,
        embedder: Embedder,
        ledger: Ledger,
        providers: dict[str, ProviderSpec],
        *,
        prefix: str = "reprise",
        # Short by default: a presigned URL embeds the access-key-id in its
        # X-Amz-Credential and is a bearer read capability for its whole life,
        # so it should outlive a page view and little else.
        serve_url_ttl: int = 300,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._ledger = ledger
        self._providers = providers
        self._prefix = prefix
        self.prefix = prefix
        self._ttl = serve_url_ttl
        self.library = B2Library(backend, prefix=prefix)

    # -- the one entry point ----------------------------------------------

    def preview(
        self, request: Request, *, before_embed: Callable[[], None] | None = None
    ) -> Decision:
        """The verdict alone: no generation, no ledger write, no side effects.

        Lets callers gate spend (rate caps, budget checks) BEFORE committing:
        a REUSE/REVIEW preview is always safe to act on, a GENERATE preview
        tells the caller that proceeding will cost money.

        `before_embed` runs immediately before the first billable embedding
        call and never at all when the exact-match path answers the request.
        A caller reserving budget outside this method would have to reserve
        unconditionally, charging a paid quota for a free lookup; raising from
        the hook (a cap refusal) stops the embedding from happening.
        """
        return self._decide(request, self.library.scan(), before_embed=before_embed)

    def _decide(
        self,
        request: Request,
        entries: list[LibraryEntry],
        *,
        before_embed: Callable[[], None] | None = None,
    ) -> Decision:
        # Free path first: exact match needs no embedding call.
        decision = decide(request, entries)
        if decision.verdict is not Verdict.REUSE:
            if before_embed is not None:
                before_embed()
            embedded = self.library.ensure_embeddings(entries, self._embedder)
            request_vec = self._embedder.embed(request.prompt)
            candidates = score_candidates(request, request_vec, embedded)
            decision = classify(request, candidates)
        return decision

    def handle(self, request: Request, decision: Decision | None = None) -> GatewayResult:
        """Act on a request. Pass a `decision` from `preview()` to reuse it.

        Re-deciding here would repeat the whole library scan AND a billed
        embedding call for the same request, so a caller that previews (to
        check a spend cap) and then handles pays twice for one answer. Passing
        the preview decision through removes that duplicate spend entirely.
        """
        if decision is None:
            decision = self._decide(request, self.library.scan())

        if decision.verdict is Verdict.REUSE:
            assert decision.candidate is not None
            url = self._serve_url(decision.candidate.entry.storage_key)
            self._ledger.record(decision)
            return GatewayResult(decision=decision, serve_url=url)

        if decision.verdict is Verdict.REVIEW:
            assert decision.candidate is not None
            self._ledger.record(decision)
            # Serve the candidate. A review asks a human whether this asset
            # substitutes for what they asked for, which cannot be judged from
            # a prompt and a similarity score. The bytes are already paid for,
            # and nothing is booked as saved until acceptance.
            url = self._serve_url(decision.candidate.entry.storage_key)
            return GatewayResult(decision=decision, serve_url=url)

        # GENERATE: run the pipeline FIRST, record after -- a failed generation
        # must surface as an error (Genblaze itself seals a failure manifest),
        # not as a ledger row claiming work that never completed.
        entry = self._generate(request)
        self._ledger.record(decision)
        url = self._serve_url(entry.storage_key)
        return GatewayResult(decision=decision, serve_url=url, new_entry=entry)

    def accept_review(
        self, decision: Decision, *, review_id: str = ""
    ) -> GatewayResult:
        """A human accepted a REVIEW candidate: serve it and book the saving."""
        if decision.verdict is not Verdict.REVIEW or decision.candidate is None:
            raise ValueError("accept_review requires a REVIEW decision with a candidate")
        url = self._serve_url(decision.candidate.entry.storage_key)
        self._ledger.record_accept(decision, review_id=review_id)
        # A REVIEW decision carries saved_usd 0.0 by construction: the money
        # only becomes real at acceptance. Report what record_accept booked, so
        # the card the user sees cannot understate the ledger it just wrote.
        booked = replace(decision, saved_usd=decision.candidate.entry.cost_usd)
        return GatewayResult(decision=booked, serve_url=url)

    def _serve_url(self, storage_key: str) -> str:
        """Mint a short-lived URL, but only for keys inside our asset tree.

        `storage_key` comes from a manifest, and a shared bucket accumulates
        manifests this app did not write. Without this containment check, a
        manifest pointing anywhere in the bucket would turn the serve path
        into a presigned-URL oracle for arbitrary objects, including the
        ledger itself.
        """
        allowed = f"{self._prefix}/assets/"
        if not storage_key.startswith(allowed):
            raise ValueError(
                f"refusing to serve {storage_key!r}: outside {allowed!r}"
            )
        return self._backend.get_url(storage_key, expires_in=self._ttl)

    # -- generation --------------------------------------------------------

    def _generate(self, request: Request) -> LibraryEntry:
        try:
            factory, model = self._providers[request.modality]
        except KeyError:
            raise ValueError(
                f"no provider configured for modality {request.modality!r}; "
                f"configured: {sorted(self._providers)}"
            ) from None
        sink = ObjectStorageSink(  # single-use by contract; fresh per run
            self._backend, prefix=self._prefix, key_strategy="content_addressable"
        )
        metadata = {
            k: v
            for k, v in (
                ("aspect_ratio", request.aspect_ratio),
                ("style", request.style),
            )
            if v is not None
        }
        result = (
            Pipeline("reprise-generate", project_id="reprise")
            .step(
                factory(),
                model=model,
                prompt=request.prompt,
                modality=Modality(request.modality),
                metadata=metadata,
            )
            .run(sink=sink, raise_on_failure=True)
        )
        manifest = Manifest.from_run(result.run)
        entries = entries_from_manifest(manifest)
        if not entries:
            raise RuntimeError(
                "generation completed but produced no reusable entry "
                f"(run {result.run.run_id}); manifest verify={manifest.verify()}"
            )
        return entries[0]

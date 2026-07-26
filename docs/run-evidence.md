# Run evidence (raw probe outputs, newest first)

All timestamps PT. Every claim below is a pasted probe result, not a paraphrase.

## 2026-07-26 ~08:20 - Genblaze -> ObjectStorageSink -> real B2, verified

Full pipeline against the live bucket (`reprise-vault-9315d5`, us-west-004,
Object Lock enabled at creation). MockProvider handed a real 1x1 PNG via
`file://` (SSRF gate allows https/file); the sink fetched, hashed, and
transferred it; manifest uploaded alongside.

```
run: f262d532-c38c-40f9-8b94-c0b8dd14740e status: completed
verify(): True  verify_hash(): True
canonical_hash: 4bc2e64f572895a14dbd66eab68261725da516028a2edd29c9214fb49a0b1a21
step cost_usd: 0.042
asset url: https://s3.us-west-004.backblazeb2.com/reprise-vault-9315d5/reprise/assets/b1/ff/b1ff9c8e...png
  sha256: b1ff9c8ea3a780bad09b346c423d2d0e46815926879b18e841d928376a946640

B2 OBJECTS UNDER reprise/:
   reprise/assets/b1/ff/b1ff9c8e...a946640.png 69 bytes
     re-hash matches: True        <- independent boto3 read-back, not via genblaze
   reprise/manifests/f262d532-c38c-40f9-8b94-c0b8dd14740e.json 1538 bytes
```

Notable: with an unfetchable asset URL the sink FAILED CLOSED
(`SinkError: 1/1 asset transfer(s) failed; manifest was not uploaded`) instead
of uploading a manifest that would fail verification. Also: `Pipeline.run()`
emits a DeprecationWarning to pass `raise_on_failure=True` (default flips in
core 0.4.0) - our code should pass it explicitly.

## 2026-07-26 ~08:15 - scoped S3 key round-trip

Master key cannot use the S3 API (deterministic `InvalidAccessKeyId: Malformed
Access Key Id` in us-west-004 AND us-west-001; master keyID is 12 chars = the
account id, S3 requires the 25-char application keyID). Scoped key
`reprise-hackathon-s3` minted via native `b2_create_key` (master holds
`writeKeys`), stored in doppler `genblaze-hackathon/prd` as
B2_KEY_ID / B2_APP_KEY / B2_BUCKET / B2_REGION (the names
`S3StorageBackend.for_backblaze()` reads natively).

```
S3 PUT+GET OK  bucket: reprise-vault-9315d5  sha256: 7ccbd6858c8f6e41 ...
S3 DELETE OK
```

Bucket created with `fileLockEnabled=True` (Object Lock is create-time-only;
needed for the append-only decision ledger). The operator's earlier
console-created key was lost-by-design (B2 shows the secret exactly once).

## 2026-07-24 ~20:00 - SDK spike (pre-pick, per hackathon-build Phase 1.4)

PyPI `genblaze` 0.4.4 project_urls -> github.com/backblaze-labs/genblaze (the
repo named in the official rules) - official surface confirmed. End-to-end
in-memory pipeline:

```
canonical_hash: 38affaa6b097af3ac7bf22ea2080260dd6d2d01d87d4a21be9fec1e6d530314e
verify_hash() -> True
```

"v0.6.0" in Devpost updates is the release WAVE name / git tag; the umbrella
package is 0.4.4 (CHANGELOG states this verbatim). We are current.

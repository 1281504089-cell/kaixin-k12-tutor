# Candidate recipe, 2026-11-16

This directory is an APFS clone of the preview3 release recipe. The previous directory and stable release are unchanged. It is a distribution-repository overlay, not the learning-source checkout. Copy only the files in the candidate recipe commit; inherited evidence is historical evidence.

The current baseline is `student-20261115-preview3`, learning source `896e79b517a008ac6d584526151862ff6191cf77`, release ID `445953276`. `fresh-install-lock.json` now pins that actual baseline's thirteen public installation files. Current and oldest-launcher update paths remain distinct native tests.

`prepare-candidate.py` requires the owner's final source HEAD, explicit isolation ledger and completed student-only bank pack. It hashes the published export, prepares a complete runtime-file manifest and makes immutable 2 MiB source/bank transport parts. The source overlay is applied only after the entire previous verified patch chain. It supports only ledger-declared physical deletions from an export checkout; other tracked dirty files fail. It never signs or uploads. Example, after final freeze:

```sh
python prepare-candidate.py --source OWNER_EXPORT --commit OWNER_HEAD --tag student-20261116-k12-ATTEMPT --baseline-source /Users/Admin1/Documents/Kaixin-20261115-聊天快速预览/source --bank /Users/Admin1/Documents/Kaixin-20261115-K12题库工程/bank-runtime-20261116 --bank-archive-prefix core/deeptutor/services/student_learning/question_bank_data --isolation-ledger OWNER_LEDGER
```

The bank is generated data inside the existing signed core, at `core/deeptutor/services/student_learning/question_bank_data/{manifest.json,index.sqlite3,student-assets/...}`. It is outside the learning-source Git inventory and inside its own hash-bound generated-payload manifest. The original staging data, teacher answers and private account files are not copied. The final pack's builder/source/staging receipts stay bound by its manifest.

The owner must provide the final signed launcher descriptor with the final core identity. Launcher script bytes remain unchanged if their existing fingerprints still match. `ci-attachment-core.py` builds every declared runtime source file, rebuilds the locked Word helper, adds the generated bank, then reads back every actual archive member and runs the bundle audit. The pending model assets are excluded by path and hash; exclusion cannot be hidden by renaming. A pending semantic-distribution item must stay explicit in the ledger and release notes.

Candidate source can be delivered through the GitHub connector's blobs/tree/commit operations. No local `gh`, copied private plugin token or client-side GitHub token is required. The runner uses its normal short-lived `github.token`. A `codex/k12-recipe-20261116-*` branch is review-only. After complete final inputs, a `codex/k12-core-20261116-*` push creates/uploads an isolated prerelease. Following core readback and local owner signatures, a `codex/k12-native-20261116-*` push runs independent Windows x64, Intel Mac and Apple Silicon Mac jobs. These names do not trigger the copied historical publication workflow.

Fresh native API checks compare full questions/options/subquestions and images to the installed pack; wrong revisions/unknown identities fail. Actual native update IPC retains existing upload/audio/formula/quick-preview gates and adds four-size source-library/history-link checks. All fixtures use explicitly marked disposable homes, public original questions and synthetic history; no model request is needed. Source/selector contracts must match the final product before the native branch is frozen. API smoke does not replace the existing authorization unit tests or claim all user hardware was tested.

`attachment-release.json` and `attachment-publication.json` remain `prepared: false` until the owner finalizes them. No old proof can satisfy the new promotion guard. The publication helper additionally requires fresh same-revision K12 API and native UI proofs on all three platforms. Only the owner may prepare/run promotion after the full matrix succeeds. Stable manifests, Latest, the installed app and USB were not changed by recipe preparation.

Local checks: `python3 -B -m unittest -v test_release_source.py`; Python AST checks; `node --check` for the three changed native scripts. These checks are offline and import no product code. They are not native acceptance results.

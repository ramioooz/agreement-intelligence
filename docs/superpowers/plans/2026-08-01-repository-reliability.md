# Repository Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably process uploaded agreements, immediately reflect uploads in the repository, and let platform administrators permanently delete agreements with a metadata-only immutable audit trail.

**Architecture:** The API and worker must share the same named SQS processing queue. A queued-job recovery endpoint republishes a durable job without altering its idempotent processing semantics. Permanent deletion is an admin-only API operation: it removes scoped agreement data and storage objects while recording a database-enforced immutable audit snapshot in a table that has no foreign key to the removed agreement.

**Tech Stack:** Next.js 16/React, FastAPI, SQLAlchemy/Alembic, PostgreSQL, boto3 S3/SQS through LocalStack, Vitest, pytest, Docker Compose.

## Global Constraints

- Implement GitHub issues #125, #126, and #127 in one branch and one ready PR; never merge `main`.
- Grant permanent deletion only through a new `agreements:delete` permission held by `platform_admin`.
- Deletion must remove source files, analysis artifacts, processing rows, and the agreement record; the audit retains only metadata and checksums.
- The deletion-audit table must reject `UPDATE` and `DELETE` at the PostgreSQL level.
- Preserve at-least-once processing: requeueing may duplicate a queue message but must not duplicate processing results.
- Add only critical regression coverage: queue config, requeue, upload refresh, authorization/deletion/audit, and missing-job message acknowledgement.

---

### Task 1: Queue delivery and stale-job recovery (#125)

**Files:**
- Modify: `compose.yaml`
- Modify: `apps/api/src/agreement_intelligence_api/processing/routes.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/service.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/repository.py`
- Modify: `apps/api/tests/test_processing_jobs.py`
- Modify: `tests/stack/test-compose-contract.sh`
- Modify: `apps/web/src/lib/processing-api.ts`
- Modify: `apps/web/src/components/agreement-detail.tsx`
- Modify: `apps/web/src/components/agreement-detail.test.tsx`

**Interfaces:**
- Produces `POST /agreements/{agreement_id}/processing-jobs/{job_id}/requeue` for authorized queued jobs.
- Produces a worker-safe acknowledgement path for a queue message whose job was removed.

- [ ] **Step 1: Write the failing API and compose checks**

```python
def test_requeue_republishes_a_queued_job(client, queue_publisher):
    response = client.post(f"/agreements/{agreement_id}/processing-jobs/{job_id}/requeue", headers=admin_headers)
    assert response.status_code == 202
    assert queue_publisher.messages == [str(job_id)]
```

```sh
assert_service_environment_contains api SQS_PROCESSING_QUEUE
assert_service_environment_contains worker SQS_PROCESSING_QUEUE
```

- [ ] **Step 2: Run the focused checks and confirm they fail because the endpoint and API Compose variable do not exist.**

Run: `uv run pytest apps/api/tests/test_processing_jobs.py -k requeue -v && tests/stack/test-compose-contract.sh`

- [ ] **Step 3: Add queue configuration and requeue behavior**

Pass `SQS_PROCESSING_QUEUE` to `api` in Compose. Extend the processing service/repository so a queued job creates a fresh outbox delivery with the same job ID and an incremented delivery attempt; dispatch it through the configured queue. Return `202`; reject jobs outside the caller scope or jobs already terminal.

- [ ] **Step 4: Add the detail action**

Render `Requeue analysis` only for a queued job. Call the same-origin web route/API helper, then refresh the route so the timeline reflects the new delivery.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest apps/api/tests/test_processing_jobs.py -k requeue -v`, `pnpm --filter @agreement-intelligence/web test -- agreement-detail.test.tsx`, and `tests/stack/test-compose-contract.sh`.

Commit: `Restore processing queue delivery`

### Task 2: Upload refresh (#126)

**Files:**
- Modify: `apps/web/src/components/agreement-upload-form.tsx`
- Modify: `apps/web/src/components/agreement-upload-form.test.tsx`

**Interfaces:**
- Produces a refreshed repository route after a successful `POST /api/agreements/upload` response.

- [ ] **Step 1: Write the failing component test**

```tsx
it("refreshes the repository after a successful upload", async () => {
  render(<AgreementUploadForm fetcher={successfulFetcher} />);
  await user.click(screen.getByRole("button", { name: "Upload agreement" }));
  expect(refresh).toHaveBeenCalledOnce();
});
```

- [ ] **Step 2: Run it and confirm it fails because the upload form does not use the router.**

Run: `pnpm --filter @agreement-intelligence/web test -- agreement-upload-form.test.tsx`

- [ ] **Step 3: Implement the minimal post-upload refresh**

Use Next navigation's router in the client component. On `201`, reset the form, call `router.refresh()`, and retain the accessible success message. Do not refresh on failure.

- [ ] **Step 4: Verify and commit**

Run: `pnpm --filter @agreement-intelligence/web test -- agreement-upload-form.test.tsx`.

Commit: `Refresh repository after upload`

### Task 3: Admin permanent deletion and immutable audit (#127)

**Files:**
- Create: `apps/api/alembic/versions/<revision>_add_agreement_deletion_audit.py`
- Modify: `apps/api/src/agreement_intelligence_api/identity/permissions.py`
- Modify: `apps/api/src/agreement_intelligence_api/agreements/models.py`
- Modify: `apps/api/src/agreement_intelligence_api/agreements/repository.py`
- Modify: `apps/api/src/agreement_intelligence_api/agreements/routes.py`
- Modify: `apps/api/src/agreement_intelligence_api/agreements/service.py`
- Modify: `apps/api/src/agreement_intelligence_api/documents/service.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/models.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/repository.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/processing.py`
- Modify: `apps/api/tests/test_agreements_api.py`
- Modify: `apps/worker/tests/test_processing.py`
- Modify: `apps/web/src/lib/agreement-api.ts`
- Modify: `apps/web/src/components/agreement-repository.tsx`
- Modify: `apps/web/src/components/agreement-repository.test.tsx`
- Modify: `apps/web/src/app/dashboard/agreements/page.tsx`
- Create: `apps/web/src/app/api/agreements/[agreementId]/route.ts`

**Interfaces:**
- Produces `DELETE /agreements/{agreement_id}` which returns `204` after complete deletion.
- Produces `agreement_deletion_audit_events` with immutable metadata: event ID, scope, removed agreement ID, title/type, file checksums, actor ID, timestamp, and outcome.

- [ ] **Step 1: Write the failing API tests**

```python
def test_reviewer_cannot_permanently_delete_an_agreement(client):
    response = client.delete(f"/agreements/{agreement_id}", headers=reviewer_headers)
    assert response.status_code == 404

def test_platform_admin_deletion_removes_data_and_keeps_immutable_audit(client, storage):
    response = client.delete(f"/agreements/{agreement_id}", headers=admin_headers)
    assert response.status_code == 204
    assert storage.deleted_keys == {source_key, artifact_key}
    assert deletion_audit_for(agreement_id).actor_id == admin_id
```

- [ ] **Step 2: Run the focused test and confirm it fails because no delete route/permission/audit table exists.**

Run: `uv run pytest apps/api/tests/test_agreements_api.py -k delete -v`

- [ ] **Step 3: Add the immutable audit migration and permission**

Create the deletion audit table without an agreement foreign key. Add a PostgreSQL trigger that raises on `UPDATE` or `DELETE`. Add `AGREEMENTS_DELETE`; grant it only through `PLATFORM_ADMIN`.

- [ ] **Step 4: Implement scoped permanent deletion**

Within the API service, authorize deletion, capture a metadata-only audit snapshot, delete processing outbox/artifact/job rows and the agreement record in one database transaction, then delete the captured source/artifact object keys idempotently. If object cleanup fails, return a controlled failure and retain the audit event with an `storage_cleanup_pending` outcome for operational follow-up; never restore the agreement after its database deletion.

- [ ] **Step 5: Make late worker messages harmless**

When a worker receives a message for a deleted job, acknowledge/delete the queue message without creating artifacts or retries. Preserve normal failure behavior for all other unexpected processing errors.

- [ ] **Step 6: Add the admin-only repository action**

Expose a `Delete` control only when the signed-in user has the delete permission. Require browser confirmation naming the agreement. On `204`, refresh the repository; on failure, show an accessible error without removing the row optimistically.

- [ ] **Step 7: Verify and commit**

Run: `uv run pytest apps/api/tests/test_agreements_api.py -k delete -v`, `uv run pytest apps/worker/tests/test_processing.py -k deleted -v`, and `pnpm --filter @agreement-intelligence/web test -- agreement-repository.test.tsx`.

Commit: `Add permanent agreement deletion`

### Task 4: Final integration verification

**Files:**
- Modify: `README.md` only if the visible local recovery workflow needs one concise instruction.

- [ ] **Step 1: Run targeted migration and stack verification**

Run: `make stack-up`, upload a small PDF, confirm it appears without a page refresh, requeue an existing stuck job, and verify a newly submitted job moves from queued to completed.

- [ ] **Step 2: Run full verification**

Run: `make check && git diff --check`

- [ ] **Step 3: Commit and raise the ready PR**

Commit any concise documentation change with `Document repository recovery`, push `feat/repository-reliability`, and open a ready PR to `main` that closes #125, #126, and #127.

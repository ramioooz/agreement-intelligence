"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { FieldHelp } from "@/components/field-help";
import type {
  PlaybookRule,
  PlaybookRuleWrite,
  PlaybookVersion,
} from "@/lib/playbook-api";

type PlaybookEditorProps = {
  playbook: PlaybookVersion;
  canManage: boolean;
  addRuleAction?: (rule: PlaybookRuleWrite) => Promise<void>;
  updateRuleAction?: (ruleId: string, rule: PlaybookRuleWrite) => Promise<void>;
  deleteRuleAction?: (ruleId: string) => Promise<void>;
  publishAction?: () => Promise<void>;
};

const emptyRule: PlaybookRuleWrite = {
  clause_type: "",
  title: "",
  policy_type: "required",
  preferred_language: "",
  fallback_language: "",
  severity: "medium",
  legal_rationale: "",
  reviewer_guidance: "",
  evaluation_config: {
    method: "deterministic",
    semantic_assessment_permitted: false,
  },
};

const clauseTypes = [
  ["limitation_of_liability", "Limitation of liability"],
  ["indemnity", "Indemnity"],
  ["confidentiality", "Confidentiality"],
  ["termination", "Term and termination"],
  ["governing_law", "Governing law"],
  ["dispute_resolution", "Dispute resolution"],
  ["data_protection", "Data protection"],
  ["intellectual_property", "Intellectual property"],
  ["payment_terms", "Payment terms"],
  ["assignment", "Assignment"],
  ["audit_rights", "Audit rights"],
  ["sanctions_and_compliance", "Sanctions and compliance"],
] as const;

const reviewerGuidanceTemplates = [
  {
    value: "escalate_to_legal",
    label: "Escalate to Legal",
    guidance:
      "Escalate to Legal for review and approval before accepting this clause.",
  },
  {
    value: "approved_fallback",
    label: "Accept approved fallback only",
    guidance:
      "Accept only if the approved fallback language is used; otherwise escalate to Legal.",
  },
  {
    value: "business_approval",
    label: "Require business-owner approval",
    guidance:
      "Obtain documented business-owner approval before accepting a deviation.",
  },
] as const;

function isPublishableRule(rule: PlaybookRuleWrite): boolean {
  return Boolean(
    rule.clause_type.trim() &&
    rule.title.trim() &&
    rule.legal_rationale.trim() &&
    rule.reviewer_guidance.trim() &&
    (rule.policy_type === "prohibited" || rule.preferred_language?.trim()),
  );
}

function messageFor(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The playbook change could not be saved. Please try again.";
}

function editableRule(
  rule: PlaybookRuleWrite | PlaybookRule,
): PlaybookRuleWrite {
  const ruleWrite = { ...rule } as PlaybookRuleWrite & { id?: string };
  delete ruleWrite.id;
  return ruleWrite;
}

type RuleFormProps = {
  heading: string;
  initialRule: PlaybookRuleWrite | PlaybookRule;
  submitLabel: string;
  submittingLabel: string;
  onSubmit: (rule: PlaybookRuleWrite) => Promise<void>;
  onDelete?: () => void;
  onDiscard?: () => void;
};

function RuleForm({
  heading,
  initialRule,
  submitLabel,
  submittingLabel,
  onSubmit,
  onDelete,
  onDiscard,
}: RuleFormProps) {
  const initialWriteRule = editableRule(initialRule);
  const [rule, setRule] = useState<PlaybookRuleWrite>(initialWriteRule);
  const [customClauseType, setCustomClauseType] = useState(
    Boolean(
      initialRule.clause_type &&
      !clauseTypes.some(([value]) => value === initialRule.clause_type),
    ),
  );
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const id = heading === "Add rule" ? "new-rule" : `rule-${heading}`;
  const isExistingRule = Boolean(onDelete);
  const hasChanges = JSON.stringify(rule) !== JSON.stringify(initialWriteRule);
  const canSubmit = isPublishableRule(rule) && (!isExistingRule || hasChanges);

  function update<K extends keyof PlaybookRuleWrite>(
    key: K,
    value: PlaybookRuleWrite[K],
  ) {
    setRule((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isPublishableRule(rule)) {
      setError(
        "Clause type, title, legal rationale, reviewer guidance, and preferred language are required for this policy.",
      );
      return;
    }
    setError(undefined);
    setSubmitting(true);
    try {
      await onSubmit({
        ...rule,
        preferred_language: rule.preferred_language?.trim() || null,
        fallback_language: rule.fallback_language?.trim() || null,
      });
      if (heading === "Add rule") setRule(emptyRule);
    } catch (submitError) {
      setError(messageFor(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  const preferredLanguageRequired = rule.policy_type !== "prohibited";

  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="rounded-2xl border border-slate-200 bg-white p-5"
    >
      <h2 className="text-xl font-semibold" id={`${id}-heading`}>
        {heading === "Add rule" ? heading : `Edit rule: ${initialRule.title}`}
      </h2>
      <form className="mt-4 grid gap-4" noValidate onSubmit={submit}>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium">
            Clause type
            <FieldHelp>
              Select the clause category the rule governs. Use Other only when
              the approved taxonomy does not contain the clause.
            </FieldHelp>
            <select
              aria-label="Clause type"
              aria-describedby={`${id}-requirements`}
              aria-invalid={Boolean(error && !rule.clause_type.trim())}
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) => {
                if (event.target.value === "custom") {
                  setCustomClauseType(true);
                  update("clause_type", "");
                  return;
                }
                setCustomClauseType(false);
                update("clause_type", event.target.value);
              }}
              required
              value={customClauseType ? "custom" : rule.clause_type}
            >
              <option value="">Select a clause type</option>
              {clauseTypes.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
              <option value="custom">Other / custom</option>
            </select>
          </label>
          {customClauseType ? (
            <label className="grid gap-1.5 text-sm font-medium">
              Custom clause type
              <input
                aria-describedby={`${id}-requirements`}
                className="rounded-lg border border-slate-300 px-3 py-2"
                onChange={(event) => update("clause_type", event.target.value)}
                required
                value={rule.clause_type}
              />
            </label>
          ) : null}
          <label className="grid gap-1.5 text-sm font-medium">
            Rule title
            <input
              aria-describedby={`${id}-requirements`}
              aria-invalid={Boolean(error && !rule.title.trim())}
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) => update("title", event.target.value)}
              required
              value={rule.title}
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Rule type
            <FieldHelp>
              Required means approved language must be present; Prohibited means
              the language must not be accepted; Preferred marks the target
              position but allows a reviewed deviation.
            </FieldHelp>
            <select
              aria-label="Rule type"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) =>
                update(
                  "policy_type",
                  event.target.value as PlaybookRuleWrite["policy_type"],
                )
              }
              value={rule.policy_type}
            >
              <option value="required">Required</option>
              <option value="prohibited">Prohibited</option>
              <option value="preferred">Preferred</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Severity
            <FieldHelp>
              Choose the business and legal impact if this rule is not met: Low,
              Medium, High, or Critical.
            </FieldHelp>
            <select
              aria-label="Severity"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) =>
                update(
                  "severity",
                  event.target.value as PlaybookRuleWrite["severity"],
                )
              }
              value={rule.severity}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </label>
        </div>
        <label className="grid gap-1.5 text-sm font-medium">
          Preferred language{" "}
          {preferredLanguageRequired ? "(required)" : "(optional)"}
          <FieldHelp>
            The approved first-choice wording. It is required unless the rule
            prohibits language rather than requiring it.
          </FieldHelp>
          <textarea
            aria-describedby={`${id}-requirements`}
            aria-invalid={Boolean(
              error &&
              preferredLanguageRequired &&
              !rule.preferred_language?.trim(),
            )}
            className="min-h-24 rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) =>
              update("preferred_language", event.target.value)
            }
            required={preferredLanguageRequired}
            value={rule.preferred_language ?? ""}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Approved fallback language (optional)
          <FieldHelp>
            An alternative position that a reviewer may accept without creating
            an exception.
          </FieldHelp>
          <textarea
            className="min-h-20 rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) =>
              update("fallback_language", event.target.value)
            }
            value={rule.fallback_language ?? ""}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Legal rationale
          <textarea
            aria-describedby={`${id}-requirements`}
            aria-invalid={Boolean(error && !rule.legal_rationale.trim())}
            className="min-h-20 rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => update("legal_rationale", event.target.value)}
            required
            value={rule.legal_rationale}
          />
        </label>
        <div className="grid gap-1.5 text-sm font-medium">
          <span>
            Reviewer guidance
            <FieldHelp>
              The practical instruction shown to a human reviewer when the
              clause is found. Choose a template to start, then tailor the text
              for this rule.
            </FieldHelp>
          </span>
          <select
            aria-label="Guidance template"
            className="rounded-lg border border-slate-300 px-3 py-2"
            defaultValue=""
            onChange={(event) => {
              const template = reviewerGuidanceTemplates.find(
                ({ value }) => value === event.target.value,
              );
              if (template) update("reviewer_guidance", template.guidance);
            }}
          >
            <option value="">Choose a guidance template (optional)</option>
            {reviewerGuidanceTemplates.map(({ label, value }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <textarea
            aria-label="Reviewer guidance"
            aria-describedby={`${id}-requirements`}
            aria-invalid={Boolean(error && !rule.reviewer_guidance.trim())}
            className="min-h-20 rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) =>
              update("reviewer_guidance", event.target.value)
            }
            required
            value={rule.reviewer_guidance}
          />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium">
            Evaluation method
            <FieldHelp>
              Deterministic uses repeatable policy checks. Semantic assessment
              uses cited LLM-assisted meaning comparison for equivalent or
              paraphrased wording.
            </FieldHelp>
            <select
              aria-label="Evaluation method"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) =>
                update("evaluation_config", {
                  ...rule.evaluation_config,
                  method: event.target.value as "deterministic" | "semantic",
                  semantic_assessment_permitted:
                    event.target.value === "semantic",
                })
              }
              value={rule.evaluation_config.method}
            >
              <option value="deterministic">Deterministic</option>
              <option value="semantic">Semantic assessment</option>
            </select>
          </label>
          <p className="self-end text-sm text-slate-600">
            {rule.evaluation_config.method === "semantic"
              ? "Semantic assessment is enabled for this rule."
              : "Semantic assessment is disabled for this rule."}
          </p>
        </div>
        <p className="text-sm text-slate-600" id={`${id}-requirements`}>
          Required policy fields are marked above. A draft cannot be published
          until every rule is complete.
        </p>
        {error ? <p role="alert">{error}</p> : null}
        <div className="flex items-center justify-between gap-3">
          <button
            className="w-fit rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting || !canSubmit}
            type="submit"
          >
            {submitting ? submittingLabel : submitLabel}
          </button>
          {onDelete || onDiscard ? (
            <button
              className="rounded-full border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800"
              onClick={onDelete ?? onDiscard}
              type="button"
            >
              {onDelete ? "Delete rule" : "Discard rule"}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function PublishedRule({ rule }: { rule: PlaybookRule }) {
  return (
    <article className="rounded-xl border border-slate-200 p-4">
      <h3 className="font-semibold">{rule.title}</h3>
      <p className="mt-1 text-sm text-slate-600">
        {rule.clause_type} · {rule.policy_type} · {rule.severity}
      </p>
      <dl className="mt-4 grid gap-3 text-sm">
        <div>
          <dt className="font-medium text-slate-500">Preferred language</dt>
          <dd className="mt-1 whitespace-pre-wrap">
            {rule.preferred_language || "Not specified"}
          </dd>
        </div>
        {rule.fallback_language ? (
          <div>
            <dt className="font-medium text-slate-500">
              Approved fallback language
            </dt>
            <dd className="mt-1 whitespace-pre-wrap">
              {rule.fallback_language}
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="font-medium text-slate-500">Legal rationale</dt>
          <dd className="mt-1 whitespace-pre-wrap">{rule.legal_rationale}</dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">Reviewer guidance</dt>
          <dd className="mt-1 whitespace-pre-wrap">{rule.reviewer_guidance}</dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">
            Evaluation configuration
          </dt>
          <dd className="mt-1">
            {rule.evaluation_config.method === "semantic"
              ? "Semantic assessment"
              : "Deterministic"}
            {" · "}
            {rule.evaluation_config.semantic_assessment_permitted
              ? "Permitted"
              : "Not permitted"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function PlaybookEditor({
  playbook,
  canManage,
  addRuleAction,
  updateRuleAction,
  deleteRuleAction,
  publishAction,
}: PlaybookEditorProps) {
  const router = useRouter();
  const [message, setMessage] = useState<string>();
  const [publishing, setPublishing] = useState(false);
  const [addingRule, setAddingRule] = useState(playbook.rules.length === 0);
  const isDraft = playbook.status === "draft";
  const canPublish =
    isDraft &&
    canManage &&
    playbook.rules.length > 0 &&
    playbook.rules.every(isPublishableRule);

  async function publish() {
    if (!publishAction) return;
    setMessage(undefined);
    setPublishing(true);
    try {
      await publishAction();
      router.refresh();
    } catch (error) {
      setMessage(messageFor(error));
    } finally {
      setPublishing(false);
    }
  }

  async function deleteRule(rule: PlaybookRule) {
    if (!deleteRuleAction) return;
    if (!window.confirm(`Delete “${rule.title}”? This cannot be undone.`))
      return;
    setMessage(undefined);
    try {
      await deleteRuleAction(rule.id);
      if (playbook.rules.length === 1) setAddingRule(true);
      router.refresh();
    } catch (error) {
      setMessage(messageFor(error));
    }
  }

  return (
    <section aria-labelledby="playbook-editor-heading" className="space-y-6">
      <header className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {playbook.agreement_family.replaceAll("_", " ")}
            </p>
            <h1
              className="mt-1 text-3xl font-semibold"
              id="playbook-editor-heading"
            >
              {playbook.name}
            </h1>
          </div>
          <span
            className={
              playbook.status === "published"
                ? "rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-900"
                : "rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900"
            }
          >
            {playbook.status === "published" ? "Published" : "Draft"} · Version{" "}
            {playbook.version}
          </span>
        </div>
        {playbook.status === "published" ? (
          <p className="mt-3 text-sm text-slate-600">
            Published playbooks are immutable policy records.
          </p>
        ) : null}
      </header>

      {playbook.rules.length ? (
        <section aria-labelledby="rules-heading" className="space-y-4">
          <h2 className="text-xl font-semibold" id="rules-heading">
            Rules
          </h2>
          {playbook.rules.map((rule) =>
            isDraft && canManage ? (
              <RuleForm
                heading={rule.id}
                initialRule={rule}
                key={rule.id}
                onDelete={() => void deleteRule(rule)}
                onSubmit={async (updatedRule) => {
                  await updateRuleAction?.(rule.id, updatedRule);
                  router.refresh();
                }}
                submitLabel="Save rule"
                submittingLabel="Saving…"
              />
            ) : (
              <PublishedRule key={rule.id} rule={rule} />
            ),
          )}
        </section>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-slate-600">
          This version does not contain any rules yet.
        </p>
      )}

      {isDraft && canManage && playbook.rules.length > 0 && !addingRule ? (
        <button
          className="mt-2 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:border-slate-500"
          onClick={() => setAddingRule(true)}
          type="button"
        >
          Add another rule
        </button>
      ) : null}

      {isDraft && canManage ? (
        <>
          {addingRule ? (
            <RuleForm
              heading="Add rule"
              initialRule={emptyRule}
              onDiscard={() => setAddingRule(false)}
              onSubmit={async (rule) => {
                await addRuleAction?.(rule);
                setAddingRule(false);
                router.refresh();
              }}
              submitLabel="Add rule"
              submittingLabel="Adding…"
            />
          ) : null}
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="text-xl font-semibold">Publish draft</h2>
            <p className="mt-2 text-sm text-slate-600">
              Publishing makes this version immutable. Complete every required
              rule field before publishing.
            </p>
            <button
              className="mt-4 rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canPublish || publishing}
              onClick={() => void publish()}
              type="button"
            >
              {publishing ? "Publishing…" : "Publish version"}
            </button>
          </section>
        </>
      ) : null}
      {isDraft && !canManage ? (
        <p className="rounded-xl border border-slate-200 bg-white p-5 text-slate-600">
          You can view this draft, but your workspace does not grant playbook
          management access.
        </p>
      ) : null}
      {message ? <p role="alert">{message}</p> : null}
    </section>
  );
}

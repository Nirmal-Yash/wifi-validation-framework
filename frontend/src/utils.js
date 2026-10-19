export const terminalStatuses = new Set([
  "COMPLETED", "FAILED", "LAB_FAILED", "CANCELLED", "ABORTED",
]);

export const toFiniteNumber = (value) => {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const numeric = typeof value === "number" ? value : Number(String(value).trim());
  return Number.isFinite(numeric) ? numeric : null;
};

export const formatNumber = (value, maximumFractionDigits = 2) => {
  const numeric = toFiniteNumber(value);
  if (numeric === null) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(numeric);
};

export const summarizeRunOutcomes = (items = []) => ({
  active: items.filter((item) => {
    const status = String(item?.lifecycle_status || "").toUpperCase();
    return status !== "" && !terminalStatuses.has(status);
  }).length,
  validated: items.filter((item) =>
    String(item?.business_outcome || "").toUpperCase() === "VALIDATED"
  ).length,
  validatedWithWarnings: items.filter((item) =>
    String(item?.business_outcome || "").toUpperCase() === "VALIDATED_WITH_WARNINGS"
  ).length,
  rejected: items.filter((item) =>
    String(item?.business_outcome || "").toUpperCase() === "REJECTED"
  ).length,
  unvalidated: items.filter((item) =>
    String(item?.business_outcome || "").toUpperCase() === "UNVALIDATED"
  ).length,
  missingOutcome: items.filter((item) =>
    !["VALIDATED", "VALIDATED_WITH_WARNINGS", "REJECTED", "UNVALIDATED"].includes(
      String(item?.business_outcome || "").toUpperCase()
    )
  ).length,
  needsReview: items.filter((item) =>
    ["REJECTED", "UNVALIDATED"].includes(String(item?.business_outcome || "").toUpperCase())
  ).length,
});

export const canExecute = (role) => ["OWNER", "ADMIN", "OPERATOR"].includes(role);
export const canAdmin = (role) => ["OWNER", "ADMIN"].includes(role);
export const canOwner = (role) => role === "OWNER";

export const formatDate = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
};

export const formatShortDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

export const formatDuration = (started, completed) => {
  if (!started || !completed) return "—";
  const start = new Date(started).getTime();
  const end = new Date(completed).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return seconds < 60 ? seconds + "s" : Math.floor(seconds / 60) + "m " + (seconds % 60) + "s";
};

export const formatBytes = (value) => {
  const bytes = toFiniteNumber(value);
  if (bytes === null || bytes < 0) return "—";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KiB";
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MiB";
  return (bytes / 1024 / 1024 / 1024).toFixed(1) + " GiB";
};

// A sample contributes to statistical summaries only when it is explicitly VALID,
// non-warm-up, numeric and finite. Raw sample tables still display every sample.
export const validSamples = (samples = []) => (Array.isArray(samples) ? samples : []).filter((sample) =>
  String(sample?.status || "").toUpperCase() === "VALID" &&
  !sample?.warmup &&
  toFiniteNumber(sample?.value) !== null
);

export const mean = (values = []) => {
  const finiteValues = (Array.isArray(values) ? values : [])
    .map(toFiniteNumber)
    .filter((value) => value !== null);
  return finiteValues.length
    ? finiteValues.reduce((sum, value) => sum + value, 0) / finiteValues.length
    : null;
};

export const metricMean = (metric) => mean(validSamples(metric?.samples || []).map((sample) => sample.value));

export const classifyTone = (value) => {
  const text = String(value || "").trim().toUpperCase();
  if (["PASS", "VALIDATED", "COMPLETED", "HEALTHY", "COMPARABLE", "IMPROVEMENT", "IMPROVED", "FIXED", "READY", "OK"].includes(text)) return "success";
  if (["VALIDATED_WITH_WARNINGS", "UNVALIDATED", "UNKNOWN", "DEGRADED", "NO_BASELINE", "SOFT_REGRESSION", "RUNNER_DISCONNECTED", "TIMED_OUT", "NOT_READY", "PENDING"].includes(text)) return "warning";
  if (["FAIL", "REJECTED", "FAILED", "LAB_FAILED", "REGRESSION", "PRODUCT_FAILED", "WORKER_CRASHED", "ERROR", "INVALID"].includes(text)) return "danger";
  if (["QUEUED", "PREPARING", "LAB_HEALTH_CHECK", "RUNNING", "FINALIZING", "IN_PROGRESS"].includes(text)) return "info";
  return "neutral";
};

export const humanizeStatus = (value) => {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value).replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
};

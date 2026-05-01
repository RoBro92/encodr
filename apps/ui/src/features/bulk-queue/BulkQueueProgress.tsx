import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  useActiveBulkQueueOperationsQuery,
  useBulkQueueOperationQuery,
  useCancelBulkQueueOperationMutation,
  useStartBulkQueueOperationMutation,
} from "../../lib/api/hooks";
import type { BulkQueueOperation, CreateBatchJobsPayload } from "../../lib/types/api";
import { titleCase } from "../../lib/utils/format";

const BULK_QUEUE_STORAGE_KEY = "encodr.activeBulkQueueOperationId";
const TERMINAL_PROGRESS_CLEAR_MS = 6000;

type BulkQueueToast = {
  id: string;
  message: string;
  tone: "success" | "warning" | "danger";
};

type BulkQueueProgressContextValue = {
  operation: BulkQueueOperation | null;
  active: boolean;
  terminal: boolean;
  modalOpen: boolean;
  startPending: boolean;
  cancelPending: boolean;
  startError: Error | null;
  cancelError: Error | null;
  toast: BulkQueueToast | null;
  start: (payload: CreateBatchJobsPayload) => Promise<BulkQueueOperation | null>;
  openModal: () => void;
  closeModal: () => void;
  cancel: () => void;
  clearToast: () => void;
};

const BulkQueueProgressContext = createContext<BulkQueueProgressContextValue | null>(null);

export function BulkQueueProgressProvider({ children }: { children: ReactNode }) {
  const [operationId, setOperationId] = useState<string | null>(() =>
    window.localStorage.getItem(BULK_QUEUE_STORAGE_KEY),
  );
  const [modalOpen, setModalOpen] = useState(false);
  const [terminalOperation, setTerminalOperation] = useState<BulkQueueOperation | null>(null);
  const [toast, setToast] = useState<BulkQueueToast | null>(null);
  const lastTerminalId = useRef<string | null>(null);
  const startInFlight = useRef(false);

  const startMutation = useStartBulkQueueOperationMutation();
  const operationQuery = useBulkQueueOperationQuery(operationId);
  const activeOperationsQuery = useActiveBulkQueueOperationsQuery();
  const cancelMutation = useCancelBulkQueueOperationMutation();

  const activeOperation = activeOperationsQuery.data?.items[0] ?? null;
  const liveOperation = operationQuery.data ?? activeOperation ?? null;
  const operation = liveOperation ?? terminalOperation;
  const active = operation ? isBulkOperationActive(operation) : false;
  const terminal = operation ? isBulkOperationTerminal(operation) : false;

  useEffect(() => {
    if (!operationId && activeOperation?.id) {
      setOperationId(activeOperation.id);
      window.localStorage.setItem(BULK_QUEUE_STORAGE_KEY, activeOperation.id);
    }
  }, [activeOperation?.id, operationId]);

  useEffect(() => {
    if (!operationQuery.isError) {
      return;
    }
    if (activeOperation?.id) {
      setOperationId(activeOperation.id);
      window.localStorage.setItem(BULK_QUEUE_STORAGE_KEY, activeOperation.id);
      return;
    }
    setOperationId(null);
    window.localStorage.removeItem(BULK_QUEUE_STORAGE_KEY);
  }, [activeOperation?.id, operationQuery.isError]);

  useEffect(() => {
    if (!liveOperation) {
      return;
    }
    if (!isBulkOperationTerminal(liveOperation)) {
      setTerminalOperation(null);
      window.localStorage.setItem(BULK_QUEUE_STORAGE_KEY, liveOperation.id);
      return;
    }

    setTerminalOperation(liveOperation);
    setOperationId(null);
    window.localStorage.removeItem(BULK_QUEUE_STORAGE_KEY);
    if (lastTerminalId.current !== liveOperation.id) {
      lastTerminalId.current = liveOperation.id;
      setToast({
        id: liveOperation.id,
        message: bulkTerminalToastMessage(liveOperation),
        tone: liveOperation.status === "completed" ? "success" : liveOperation.status === "failed" ? "danger" : "warning",
      });
    }
  }, [liveOperation]);

  useEffect(() => {
    if (!terminalOperation || modalOpen) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setTerminalOperation((current) => (current?.id === terminalOperation.id ? null : current));
    }, TERMINAL_PROGRESS_CLEAR_MS);
    return () => window.clearTimeout(timeout);
  }, [modalOpen, terminalOperation]);

  const openModal = useCallback(() => {
    if (operation) {
      setModalOpen(true);
    }
  }, [operation]);

  const closeModal = useCallback(() => {
    setModalOpen(false);
  }, []);

  const start = useCallback(
    async (payload: CreateBatchJobsPayload) => {
      if ((operation && isBulkOperationActive(operation)) || startInFlight.current) {
        setModalOpen(true);
        return operation;
      }
      startInFlight.current = true;
      try {
        const next = await startMutation.mutateAsync(payload);
        setTerminalOperation(null);
        setOperationId(next.id);
        window.localStorage.setItem(BULK_QUEUE_STORAGE_KEY, next.id);
        setModalOpen(true);
        return next;
      } finally {
        startInFlight.current = false;
      }
    },
    [operation, startMutation],
  );

  const cancel = useCallback(() => {
    if (!operation || !isBulkOperationActive(operation)) {
      return;
    }
    cancelMutation.mutate(operation.id);
  }, [cancelMutation, operation]);

  const value = useMemo<BulkQueueProgressContextValue>(
    () => ({
      operation,
      active,
      terminal,
      modalOpen,
      startPending: startMutation.isPending || startInFlight.current,
      cancelPending: cancelMutation.isPending,
      startError: startMutation.error instanceof Error ? startMutation.error : null,
      cancelError: cancelMutation.error instanceof Error ? cancelMutation.error : null,
      toast,
      start,
      openModal,
      closeModal,
      cancel,
      clearToast: () => setToast(null),
    }),
    [
      active,
      cancel,
      cancelMutation.error,
      cancelMutation.isPending,
      closeModal,
      modalOpen,
      openModal,
      operation,
      start,
      startMutation.error,
      startMutation.isPending,
      terminal,
      toast,
    ],
  );

  return (
    <BulkQueueProgressContext.Provider value={value}>
      {children}
    </BulkQueueProgressContext.Provider>
  );
}

export function useBulkQueueProgress() {
  const context = useContext(BulkQueueProgressContext);
  if (!context) {
    throw new Error("useBulkQueueProgress must be used within BulkQueueProgressProvider");
  }
  return context;
}

export function BulkQueueProgressIndicator({ operation, onOpen }: { operation: BulkQueueOperation; onOpen: () => void }) {
  const summary = bulkProgressSummary(operation);
  return (
    <button className={`bulk-progress-sidebar bulk-progress-sidebar-${operation.status}`} type="button" onClick={onOpen}>
      <span className="bulk-progress-sidebar-heading">{isBulkOperationTerminal(operation) ? bulkTerminalTitle(operation) : "Adding to queue"}</span>
      <span className="bulk-progress-sidebar-detail">{summary.countsLabel}</span>
      <span className="bulk-progress-sidebar-bar" role="progressbar" aria-label="Bulk queue progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={summary.percent}>
        <span style={{ width: `${summary.percent}%` }} />
      </span>
      <span className="bulk-progress-sidebar-status">{summary.statusLabel}</span>
    </button>
  );
}

export function BulkQueueToast({ toast, onDismiss }: { toast: BulkQueueToast; onDismiss: () => void }) {
  return (
    <div className={`bulk-toast bulk-toast-${toast.tone}`} role="status">
      <span>{toast.message}</span>
      <button className="alert-dismiss-button" type="button" aria-label="Dismiss" onClick={onDismiss}>
        x
      </button>
    </div>
  );
}

export function BulkQueueProgressModal({
  operation,
  cancelling,
  onClose,
  onCancel,
}: {
  operation: BulkQueueOperation;
  cancelling: boolean;
  onClose: () => void;
  onCancel: () => void;
}) {
  const summary = bulkProgressSummary(operation);
  const active = isBulkOperationActive(operation);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Adding to queue">
      <section className="modal-panel">
        <div className="card-stack">
          <div className="bulk-modal-heading">
            <strong>{active ? "Adding to queue" : bulkTerminalTitle(operation)}</strong>
            <p className="muted-copy">{summary.statusLabel}</p>
          </div>

          <ol className="bulk-stage-list" aria-label="Bulk queue stages">
            {bulkStages.map((stage) => (
              <li key={stage.key} className={bulkStageIsCurrent(operation, stage.key) ? "bulk-stage-current" : ""}>
                <span className="bulk-stage-index">{stage.index}</span>
                <span className="bulk-stage-label">{stage.label}</span>
              </li>
            ))}
          </ol>

          <div className="bulk-progress-meter">
            <div className="bulk-progress-bar" role="progressbar" aria-label="Bulk queue progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={summary.percent}>
              <span style={{ width: `${summary.percent}%` }} />
            </div>
            <div className="bulk-progress-summary">
              <strong>{summary.countsLabel}</strong>
              <span>{summary.outcomeLabel}</span>
            </div>
          </div>

          <div className="metric-grid">
            <div className="metric-panel">
              <span className="metric-label">Queued</span>
              <strong>{operation.queued_count}</strong>
            </div>
            <div className="metric-panel">
              <span className="metric-label">Skipped</span>
              <strong>{operation.skipped_count}</strong>
            </div>
            <div className="metric-panel">
              <span className="metric-label">Blocked</span>
              <strong>{operation.blocked_count}</strong>
            </div>
            <div className="metric-panel">
              <span className="metric-label">Failed</span>
              <strong>{operation.failed_count}</strong>
            </div>
          </div>

          {operation.error_summary ? (
            <div className="info-strip info-strip-warning">
              <strong>Error summary</strong>
              <span>{operation.error_summary}</span>
            </div>
          ) : null}

          <div className="section-card-actions">
            {active ? (
              <button className="button button-secondary" type="button" onClick={onCancel} disabled={cancelling || operation.status === "cancelling"}>
                {cancelling || operation.status === "cancelling" ? "Cancelling..." : "Cancel"}
              </button>
            ) : null}
            <button className="button button-primary" type="button" onClick={onClose}>
              {active ? "Close" : "Done"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

export function isBulkOperationActive(operation: BulkQueueOperation) {
  return ["pending", "running", "cancelling"].includes(operation.status);
}

export function isBulkOperationTerminal(operation: BulkQueueOperation) {
  return ["completed", "failed", "cancelled"].includes(operation.status);
}

export function bulkProgressSummary(operation: BulkQueueOperation) {
  const total = Math.max(operation.total_expected, operation.discovered_count, operation.queued_count + operation.skipped_count + operation.blocked_count + operation.failed_count);
  const processed = operation.queued_count + operation.skipped_count + operation.blocked_count + operation.failed_count;
  const percent = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  return {
    total,
    processed,
    percent,
    countsLabel: `${operation.queued_count} / ${total} files queued`,
    outcomeLabel: `${operation.queued_count} queued, ${operation.skipped_count} skipped, ${operation.blocked_count} blocked, ${operation.failed_count} failed`,
    statusLabel: bulkProgressStatusLabel(operation),
  };
}

function bulkTerminalToastMessage(operation: BulkQueueOperation) {
  const outcome = bulkProgressSummary(operation).outcomeLabel;
  if (operation.status === "completed") {
    return `Queue add complete: ${outcome}.`;
  }
  if (operation.status === "cancelled") {
    return `Queue add cancelled: ${outcome}.`;
  }
  return `Queue add failed: ${outcome}.`;
}

function bulkTerminalTitle(operation: BulkQueueOperation) {
  if (operation.status === "completed") {
    return "Jobs created";
  }
  if (operation.status === "cancelled") {
    return "Queue add cancelled";
  }
  if (operation.status === "failed") {
    return "Queue add failed";
  }
  return "Adding to queue";
}

function bulkProgressStatusLabel(operation: BulkQueueOperation) {
  if (operation.status === "completed") {
    return "Completed";
  }
  if (operation.status === "cancelled") {
    return operation.status_text ?? "Cancelled";
  }
  if (operation.status === "failed") {
    return operation.status_text ?? "Failed";
  }
  if (operation.stage === "sending_to_queue" && operation.total_batches > 0) {
    return `Adding batch ${operation.current_batch} of ${operation.total_batches}`;
  }
  return operation.status_text ?? titleCase(operation.stage.replace(/_/g, " "));
}

function bulkStageIsCurrent(operation: BulkQueueOperation, stage: string) {
  if (stage === "completed") {
    return isBulkOperationTerminal(operation);
  }
  return operation.stage === stage;
}

const bulkStages = [
  { key: "scanning_selection", label: "Scanning selection", index: "1" },
  { key: "itemising_files", label: "Itemising files", index: "2" },
  { key: "sending_to_queue", label: "Sending to queue", index: "3" },
  { key: "completed", label: "Completed", index: "4" },
];

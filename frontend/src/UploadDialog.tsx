import "./upload.css";
import { useEffect, useRef, useState } from "react";
import { FileText, LoaderCircle, ShieldCheck, Upload, X } from "lucide-react";
import { fileSize } from "./document-types";
import type { ImportAccepted, KnowledgeDocument } from "./document-types";
import { uploadDocument } from "./api";
import { checkUploadFiles } from "./upload-fingerprints";
import type { UploadCheck } from "./upload-fingerprints";

type Props = {
  open: boolean;
  documents: KnowledgeDocument[];
  onClose: () => void;
  onImported: (files: ImportAccepted[]) => Promise<void>;
  onViewDocument: (document: KnowledgeDocument) => void;
};

export default function UploadDialog({
  open,
  documents,
  onClose,
  onImported,
  onViewDocument,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [result, setResult] = useState<UploadCheck | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [outcomes, setOutcomes] = useState<
    { filename: string; error?: string; duplicate?: boolean }[]
  >([]);
  const uploadIds = useRef(new Map<string, string>());
  const generation = useRef(0);

  useEffect(() => {
    generation.current += 1;
    if (open) {
      setFiles([]);
      setResult(null);
      setError("");
      setChecking(false);
      setDragging(false);
      setSubmitting(false);
      setOutcomes([]);
      uploadIds.current.clear();
      if (input.current) input.current.value = "";
      dialog.current?.showModal();
    } else dialog.current?.close();
    return () => {
      request.current?.abort();
    };
  }, [open]);

  async function check(list: File[]): Promise<UploadCheck | null> {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setResult(null);
    setError("");
    setChecking(true);
    try {
      const checked = await checkUploadFiles(
        list,
        documents,
        undefined,
        controller.signal,
      );
      if (controller.signal.aborted) return null;
      setResult(checked);
      return checked;
    } catch {
      if (!controller.signal.aborted)
        setError("暂时无法完成重复文件检查，请稍后重试。");
      return null;
    } finally {
      if (!controller.signal.aborted) setChecking(false);
    }
  }

  function choose(list: File[]) {
    if (submitting) return;
    request.current?.abort();
    setFiles([]);
    setResult(null);
    setError("");
    setChecking(false);
    setOutcomes([]);
    const invalid = list.find(
      (f) =>
        !/\.(pdf|docx|md|png|jpg|jpeg)$/i.test(f.name) ||
        f.size === 0 ||
        f.size > 20 * 1024 * 1024,
    );
    if (invalid) {
      setError(
        `“${invalid.name}”不符合要求，请选择非空且不超过 20 MB 的 PDF、DOCX、MD、PNG 或 JPG/JPEG。`,
      );
      return;
    }
    setFiles(list);
    if (list.length) void check(list);
  }

  async function submit() {
    if (checking || submitting || !result?.accepted.length) return;
    const checked = await check(files);
    if (!checked?.accepted.length) return;
    const run = generation.current;
    setSubmitting(true);
    setOutcomes([]);
    const accepted: ImportAccepted[] = [];
    const completed: {
      filename: string;
      error?: string;
      duplicate?: boolean;
    }[] = [];
    for (const item of checked.accepted) {
      const id = uploadIds.current.get(item.sha256) ?? crypto.randomUUID();
      uploadIds.current.set(item.sha256, id);
      try {
        const value = await uploadDocument(item.file, id);
        accepted.push(value);
        completed.push({
          filename: item.file.name,
          duplicate: value.duplicate,
        });
      } catch (failure) {
        completed.push({
          filename: item.file.name,
          error:
            failure instanceof Error ? failure.message : "上传失败，请重试。",
        });
      }
      if (run === generation.current) setOutcomes([...completed]);
    }
    if (accepted.length) await onImported(accepted);
    if (run !== generation.current) return;
    setSubmitting(false);
    if (completed.every((item) => !item.error)) onClose();
  }

  return (
    <dialog
      ref={dialog}
      className="upload-dialog"
      aria-labelledby="upload-title"
      onCancel={(e) => {
        // The file input's cancel event bubbles; only the dialog's own Escape cancels it.
        if (e.target === e.currentTarget) {
          e.preventDefault();
          onClose();
        }
      }}
      onClick={(e) => {
        if (e.target === dialog.current) onClose();
      }}
    >
      <div className="dialog-header">
        <div>
          <span className="eyebrow">知识库 / 文档导入</span>
          <h2 id="upload-title">添加知识文档</h2>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="关闭上传弹窗"
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </div>
      <p className="dialog-description">相同文件只保留一份，上传后自动处理。</p>
      <button
        type="button"
        disabled={submitting}
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onClick={() => {
          if (input.current) input.current.value = "";
          input.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(Array.from(e.dataTransfer.files));
        }}
      >
        <span className="upload-glyph">
          <Upload size={25} />
        </span>
        <strong>
          {files.length
            ? `已选择 ${files.length} 个文件`
            : "点击选择，或将文档拖到这里"}
        </strong>
        <span>PDF、DOCX、Markdown、PNG、JPG/JPEG · 单个文件最大 20 MB</span>
      </button>
      <input
        ref={input}
        disabled={submitting}
        className="sr-only"
        aria-label="选择知识文档"
        type="file"
        multiple
        accept=".pdf,.docx,.md,.png,.jpg,.jpeg"
        onChange={(e) => choose(Array.from(e.target.files ?? []))}
      />
      {files.length > 0 && (
        <div className="selected-files" aria-busy={checking}>
          {files.map((file, i) => (
            <div key={`${file.name}-${i}`}>
              <FileText size={17} />
              <span>{file.name}</span>
              <small>{fileSize(file.size)}</small>
            </div>
          ))}
        </div>
      )}
      {checking && (
        <p className="upload-check-status" role="status">
          <LoaderCircle size={16} className="spinning" />
          正在检查重复文件…
        </p>
      )}
      {result && (
        <div className="duplicate-results" role="status" aria-live="polite">
          {result.duplicates.length > 0 && (
            <p>发现 {result.duplicates.length} 份重复文件，将跳过导入。</p>
          )}
          {result.duplicates.map((item, index) => {
            const existing = documents.find(
              (doc) => doc.id === item.existing.document_id,
            );
            return (
              <div className="duplicate-file" key={`${item.sha256}-${index}`}>
                <span>
                  <strong>{item.file.name}</strong>
                  {item.reason === "batch"
                    ? `与本批次的“${item.existing.title}”内容相同`
                    : `文档已存在：“${item.existing.title}”`}
                </span>
                {existing && (
                  <button
                    type="button"
                    className="duplicate-view"
                    onClick={() => {
                      onClose();
                      onViewDocument(existing);
                    }}
                  >
                    查看已有文档
                  </button>
                )}
              </div>
            );
          })}
          <p>
            {result.accepted.length
              ? `${result.accepted.length} 份文件可以导入。`
              : "没有需要重复导入的文件。"}
          </p>
        </div>
      )}
      {error && (
        <div role="alert" className="form-error">
          {error}
          {files.length > 0 && (
            <button
              type="button"
              className="duplicate-view"
              onClick={() => {
                void check(files);
              }}
            >
              重新检查
            </button>
          )}
        </div>
      )}
      {outcomes.length > 0 && (
        <div className="upload-outcomes" aria-live="polite">
          {outcomes.map((item, index) => (
            <p
              key={index}
              className={item.error ? "form-error" : "upload-check-status"}
              role={item.error ? "alert" : "status"}
            >
              {item.filename}：
              {item.error ??
                (item.duplicate ? "文档已存在，已跳过" : "原件已保存")}
            </p>
          ))}
        </div>
      )}
      <div className="demo-notice">
        <ShieldCheck size={18} />
        <p>
          {submitting
            ? "正在保存文件，关闭窗口不影响已提交的上传。"
            : "上传后自动处理，文档就绪后即可在问答中使用。"}
        </p>
      </div>
      <div className="dialog-actions">
        <button type="button" className="secondary-button" onClick={onClose}>
          {submitting ? "关闭" : "取消"}
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={checking || submitting || !result?.accepted.length}
          onClick={() => {
            void submit();
          }}
        >
          <Upload size={16} />
          {submitting
            ? "正在上传…"
            : checking
              ? "正在检查…"
              : result?.accepted.length
                ? `上传 ${result.accepted.length} 份文档`
                : "开始上传"}
        </button>
      </div>
    </dialog>
  );
}

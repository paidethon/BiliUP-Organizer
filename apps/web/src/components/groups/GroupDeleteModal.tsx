import type { Group } from "../../api";
import { Button, Modal } from "../ui";

export function GroupDeleteModal({
  group,
  onClose,
  onConfirm,
  pending,
  error,
}: {
  group: Group | null;
  onClose: () => void;
  onConfirm: () => void;
  pending: boolean;
  error: string;
}) {
  return (
    <Modal open={group != null} title="删除分组" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <p>
          确定删除分组 <strong className="text-amber-300">{group?.name}</strong> 吗？
        </p>
        <p className="text-xs text-slate-400 bg-slate-900/60 rounded-lg px-3 py-2">
          该分组内的 {group?.up_count ?? 0} 个 UP 主将变为「未分组」，此操作不可撤销。
          B 站侧的关注与原生标签不受影响。
        </p>
        {error && (
          <p className="text-xs text-red-400" role="alert">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} aria-label="取消删除">
            取消
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={pending} aria-label={`确认删除分组 ${group?.name ?? ""}`}>
            {pending ? "删除中…" : "确认删除"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

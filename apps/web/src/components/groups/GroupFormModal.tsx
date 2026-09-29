import { useEffect, useState, type FormEvent } from "react";
import type { Group } from "../../api";
import { Button, Input, Modal } from "../ui";

export const GROUP_PALETTE = [
  "#6366f1",
  "#22d3ee",
  "#34d399",
  "#fbbf24",
  "#f87171",
  "#f472b6",
  "#a78bfa",
  "#94a3b8",
];

export interface GroupFormValues {
  name: string;
  color: string;
  sort_order: number;
  is_important: boolean;
  description: string;
}

export function GroupFormModal({
  open,
  editing,
  onClose,
  onSubmit,
  pending,
  error,
}: {
  open: boolean;
  editing: Group | null;
  onClose: () => void;
  onSubmit: (values: GroupFormValues) => void;
  pending: boolean;
  error: string;
}) {
  const [values, setValues] = useState<GroupFormValues>({
    name: "",
    color: GROUP_PALETTE[0],
    sort_order: 0,
    is_important: false,
    description: "",
  });

  useEffect(() => {
    if (!open) return;
    setValues(
      editing
        ? {
            name: editing.name,
            color: editing.color || GROUP_PALETTE[0],
            sort_order: editing.sort_order,
            is_important: editing.is_important,
            description: editing.description,
          }
        : { name: "", color: GROUP_PALETTE[0], sort_order: 0, is_important: false, description: "" },
    );
  }, [open, editing]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!values.name.trim()) return;
    onSubmit({ ...values, name: values.name.trim() });
  }

  return (
    <Modal open={open} title={editing ? `编辑分组：${editing.name}` : "新建分组"} onClose={onClose}>
      <form className="space-y-4" onSubmit={submit}>
        <label className="block text-sm">
          <span className="text-slate-400">名称（必填）</span>
          <Input
            value={values.name}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
            maxLength={64}
            required
            aria-label="分组名称"
            className="mt-1 w-full"
          />
        </label>

        <fieldset>
          <legend className="text-sm text-slate-400 mb-1">颜色</legend>
          <div className="flex flex-wrap gap-2">
            {GROUP_PALETTE.map((c) => (
              <button
                key={c}
                type="button"
                aria-label={`选择颜色 ${c}${values.color === c ? "（已选中）" : ""}`}
                aria-pressed={values.color === c}
                onClick={() => setValues((v) => ({ ...v, color: c }))}
                className={`w-7 h-7 rounded-full border-2 transition-transform ${
                  values.color === c ? "border-white scale-110" : "border-transparent"
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
        </fieldset>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={values.is_important}
            onChange={(e) => setValues((v) => ({ ...v, is_important: e.target.checked }))}
            aria-label="标记为重要分组"
          />
          <span>
            重要分组
            <span className="text-xs text-slate-500 ml-1">（重要分组的成员会优先出现在断更提醒中）</span>
          </span>
        </label>

        <label className="block text-sm">
          <span className="text-slate-400">描述</span>
          <Input
            value={values.description}
            onChange={(e) => setValues((v) => ({ ...v, description: e.target.value }))}
            aria-label="分组描述"
            className="mt-1 w-full"
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-400">排序值（越小越靠前）</span>
          <Input
            type="number"
            value={values.sort_order}
            onChange={(e) => setValues((v) => ({ ...v, sort_order: Number(e.target.value) || 0 }))}
            aria-label="排序值"
            className="mt-1 w-32"
          />
        </label>

        {error && (
          <p className="text-xs text-red-400" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" type="button" onClick={onClose} aria-label="取消">
            取消
          </Button>
          <Button variant="primary" type="submit" disabled={pending || !values.name.trim()} aria-label={editing ? "保存修改" : "创建分组"}>
            {pending ? "保存中…" : editing ? "保存" : "创建"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

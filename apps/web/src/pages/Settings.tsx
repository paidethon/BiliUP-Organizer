import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { SectionCard } from "../components/settings/SectionCard";
import {
  AiSectionForm,
  LumirssSectionForm,
  RemindersSectionForm,
  SmtpSectionForm,
  SyncSectionForm,
  type SettingsData,
} from "../components/settings/sections";

type SectionKey = "ai" | "smtp" | "lumirss" | "reminders" | "sync";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

export default function Settings() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SettingsData>("/settings"),
  });

  // 每个分区独立的保存状态
  const [savingSection, setSavingSection] = useState<SectionKey | null>(null);
  const [savedSection, setSavedSection] = useState<SectionKey | null>(null);
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<SectionKey, string>>>({});

  useEffect(() => {
    if (savedSection == null) return;
    const timer = window.setTimeout(() => setSavedSection(null), 4000);
    return () => window.clearTimeout(timer);
  }, [savedSection]);

  const saveMutation = useMutation({
    mutationFn: (vars: { section: SectionKey; body: Record<string, unknown> }) =>
      api<Record<string, unknown>>(`/settings/${vars.section}`, { method: "PUT", body: vars.body }),
    onSuccess: (res, vars) => {
      setSavedSection(vars.section);
      setSectionErrors((prev) => ({ ...prev, [vars.section]: undefined }));
      // 只回写已保存分区，避免其他分区未保存的草稿被服务端数据重置
      queryClient.setQueryData<SettingsData>(["settings"], (old) =>
        old ? ({ ...old, [vars.section]: { ...res } } as SettingsData) : old,
      );
    },
    onError: (err, vars) => {
      setSectionErrors((prev) => ({ ...prev, [vars.section]: errText(err, "保存失败，请重试") }));
    },
  });

  function save(section: SectionKey, body: Record<string, unknown>) {
    setSavingSection(section);
    saveMutation.mutate(
      { section, body },
      { onSettled: () => setSavingSection(null) },
    );
  }

  const formProps = (key: SectionKey) => ({
    saving: savingSection === key,
    saved: savedSection === key,
    error: sectionErrors[key] ?? null,
    onSave: (body: Record<string, unknown>) => save(key, body),
  });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">设置</h1>
        <span className="text-xs text-slate-500">点击分区标题展开，密钥字段留空表示保持不变</span>
      </header>

      {isLoading && <Spinner label="正在加载设置…" />}
      {error && <ErrorState message={errText(error, "加载设置失败")} />}
      {data && Object.keys(data).length === 0 && <EmptyState title="暂无可配置项" />}

      {data && (
        <div className="space-y-3">
          <SectionCard title="AI 分类" description="OpenAI 兼容接口，为未分组 UP 生成归类建议" configured={data.ai?.configured}>
            <AiSectionForm value={data.ai} {...formProps("ai")} />
          </SectionCard>
          <SectionCard title="邮件（SMTP）" description="提醒与每周周报的发信通道" configured={data.smtp?.configured}>
            <SmtpSectionForm value={data.smtp} {...formProps("smtp")} />
          </SectionCard>
          <SectionCard title="LumiRSS" description="对接 LumiRSS 收件箱" configured={data.lumirss?.configured}>
            <LumirssSectionForm value={data.lumirss} {...formProps("lumirss")} />
          </SectionCard>
          <SectionCard title="提醒阈值" description="各类提醒规则的触发阈值">
            <RemindersSectionForm value={data.reminders} {...formProps("reminders")} />
          </SectionCard>
          <SectionCard title="同步" description="B 站数据同步频率与观看历史抓取">
            <SyncSectionForm value={data.sync} {...formProps("sync")} />
          </SectionCard>
        </div>
      )}
    </div>
  );
}

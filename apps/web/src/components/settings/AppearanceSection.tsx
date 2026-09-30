import { useTheme, type ThemeChoice } from "../../theme";
import { Card } from "../ui";

const CHOICES: { key: ThemeChoice; label: string }[] = [
  { key: "light", label: "浅色" },
  { key: "dark", label: "深色" },
  { key: "system", label: "跟随系统" },
];

/** Browser-local appearance preference; intentionally not a server setting. */
export function AppearanceSection() {
  const [choice, applied, setChoice] = useTheme();
  return (
    <Card className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">外观</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          主题保存在当前浏览器，当前生效：{applied === "dark" ? "深色" : "浅色"}
        </p>
      </div>
      <div className="flex gap-2" role="group" aria-label="选择主题">
        {CHOICES.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={choice === item.key}
            onClick={() => setChoice(item.key)}
            className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
              choice === item.key
                ? "border-indigo-400 text-indigo-300 bg-indigo-500/10"
                : "border-slate-700 text-slate-400 hover:text-white"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

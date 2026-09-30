import { useState } from "react";
import { getGlass, setGlass, useTheme, type ThemeChoice } from "../../theme";
import { Card } from "../ui";

const CHOICES: { key: ThemeChoice; label: string }[] = [
  { key: "light", label: "浅色" },
  { key: "dark", label: "深色" },
  { key: "system", label: "跟随系统" },
];

/** Browser-local appearance preferences; intentionally not server settings. */
export function AppearanceSection() {
  const [choice, applied, setChoice] = useTheme();
  const [glass, setGlassState] = useState<number>(() => getGlass());

  function onGlassChange(value: number) {
    setGlassState(value);
    setGlass(value);
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold">外观</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          主题与毛玻璃保存在当前浏览器，当前生效：{applied === "dark" ? "深色" : "浅色"}
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
      <div>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <label htmlFor="glass-blur">毛玻璃强度</label>
          <span className="tabular-nums" aria-hidden="true">
            {glass === 0 ? "关闭" : `${glass} px`}
          </span>
        </div>
        <input
          id="glass-blur"
          type="range"
          min={0}
          max={24}
          step={2}
          value={glass}
          onChange={(e) => onGlassChange(Number(e.target.value))}
          aria-valuetext={glass === 0 ? "关闭" : `${glass} 像素`}
          className="mt-2 w-full accent-indigo-500"
        />
        <p className="text-xs text-slate-600 mt-1">调到 0 可完全关闭毛玻璃（低性能设备推荐）</p>
      </div>
    </Card>
  );
}

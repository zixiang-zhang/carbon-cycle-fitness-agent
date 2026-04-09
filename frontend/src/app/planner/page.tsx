"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { reportApi } from "@/lib/api";
import { userStorage } from "@/lib/storage";
import { ReportSummary, WeightChartPoint } from "@/lib/types";

const GlassCard = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => <div className={`glass-card p-6 ${className}`}>{children}</div>;

function WeightTrendChart({ data }: { data: WeightChartPoint[] }) {
  if (data.length < 2) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        记录更多体重数据后即可查看趋势
      </div>
    );
  }

  const minWeight = Math.min(...data.map((item) => item.value)) - 1;
  const maxWeight = Math.max(...data.map((item) => item.value)) + 1;
  const range = Math.max(maxWeight - minWeight, 1);
  const width = 100;
  const height = 60;
  const padding = 10;

  const points = data.map((item, index) => {
    const x = padding + (index / (data.length - 1)) * (width - padding * 2);
    const y =
      height -
      padding -
      ((item.value - minWeight) / range) * (height - padding * 2);
    return { ...item, x, y };
  });

  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");

  return (
    <div className="h-full flex flex-col">
      <svg viewBox={`0 0 ${width} ${height}`} className="flex-1 w-full">
        <path
          d={path}
          fill="none"
          stroke="url(#weightGradient)"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {points.map((point) => (
          <circle
            key={point.date}
            cx={point.x}
            cy={point.y}
            r={2}
            fill="white"
            stroke="hsl(var(--primary))"
            strokeWidth={1.5}
          />
        ))}
        <defs>
          <linearGradient id="weightGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(var(--primary))" />
            <stop offset="100%" stopColor="hsl(var(--accent))" />
          </linearGradient>
        </defs>
      </svg>
      <div className="flex justify-between text-[10px] text-muted-foreground mt-2">
        {points.map((point) => (
          <span key={point.date}>{point.date.slice(5)}</span>
        ))}
      </div>
      <div className="text-center mt-3">
        <span className="text-3xl font-black text-primary">
          {data[data.length - 1]?.value.toFixed(1)}
        </span>
        <span className="text-sm text-muted-foreground ml-1">kg</span>
      </div>
    </div>
  );
}

export default function PlannerHistoryPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [weightHistory, setWeightHistory] = useState<WeightChartPoint[]>([]);

  useEffect(() => {
    const userId = userStorage.getUserId();
    if (!userId) {
      router.push("/login");
      return;
    }

    const load = async () => {
      try {
        const [reportList, weights] = await Promise.all([
          reportApi.listByUser(userId).catch(() => []),
          reportApi.getWeightHistory(userId).catch(() => []),
        ]);
        setReports(reportList);
        setWeightHistory(weights);
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [router]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-primary animate-pulse text-xl font-bold">
        正在加载历史数据...
      </div>
    );
  }

  return (
    <div className="max-w-[1200px] mx-auto p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-black text-primary">历史周报与体重趋势</h1>
          <p className="text-muted-foreground mt-1">
            所有周报和体重曲线都来自真实后端数据
          </p>
        </div>
        <button
          onClick={() => router.push("/report")}
          className="px-4 py-2 rounded-xl bg-primary/10 hover:bg-primary/20 text-primary font-bold text-sm transition-colors"
        >
          查看本周报告
        </button>
      </div>

      <GlassCard className="h-64">
        <h2 className="text-lg font-extrabold text-primary mb-4">体重趋势</h2>
        <div className="h-[calc(100%-2rem)]">
          <WeightTrendChart data={weightHistory} />
        </div>
      </GlassCard>

      <GlassCard>
        <h2 className="text-lg font-extrabold text-primary mb-4">历史周报</h2>

        {reports.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            暂无历史周报，先生成一份本周复盘吧。
          </div>
        ) : (
          <div className="space-y-3">
            {reports.map((report) => (
              <div
                key={report.id}
                onClick={() => router.push(`/report?week=${report.id}`)}
                className="flex items-center gap-4 p-4 rounded-xl bg-secondary/30 hover:bg-secondary/50 cursor-pointer transition-colors group"
              >
                <div className="min-w-[140px]">
                  <div className="font-bold text-sm">
                    {report.week_start.slice(5)} - {report.week_end.slice(5)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(report.created_at).toLocaleDateString("zh-CN")}
                  </div>
                </div>

                <div className="flex-1 flex items-center gap-6 text-sm">
                  <div>
                    依从度{" "}
                    <span className="font-bold text-emerald-600">
                      {report.overall_adherence.toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    趋势{" "}
                    <span className="font-bold text-primary">{report.trend}</span>
                  </div>
                  <div>
                    体重变化{" "}
                    <span className="font-bold text-rose-500">
                      {report.weight_change === null || report.weight_change === undefined
                        ? "--"
                        : `${report.weight_change > 0 ? "+" : ""}${report.weight_change.toFixed(1)}kg`}
                    </span>
                  </div>
                </div>

                <span className="text-muted-foreground group-hover:text-primary transition-colors">
                  查看
                </span>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}

"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { logApi, planApi, reportApi, weightApi } from "@/lib/api";
import { userStorage } from "@/lib/storage";
import {
  CarbonCyclePlan,
  LogStats,
  ReportDetail,
  WeeklyStatsInput,
  WeightChartPoint,
} from "@/lib/types";

const GlassCard = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => <div className={`glass-card p-6 ${className}`}>{children}</div>;

function buildWeeklyStats(
  plan: CarbonCyclePlan | null,
  logStats: LogStats | null,
  weights: WeightChartPoint[],
): WeeklyStatsInput | null {
  if (!plan) {
    return null;
  }

  const weekDays = plan.days.slice(0, 7);
  const totalTarget = weekDays.reduce(
    (sum, day) =>
      sum +
      day.macros.protein_g * 4 +
      day.macros.carbs_g * 4 +
      day.macros.fat_g * 9,
    0,
  );
  const calorieTarget = weekDays.length ? totalTarget / weekDays.length : 0;
  const trainingTotal = weekDays.filter((day) => day.training_scheduled).length;
  const trainingCompleted = logStats
    ? Math.round((logStats.training_completion_rate / 100) * trainingTotal)
    : 0;

  const weightStart = weights[0]?.value ?? null;
  const weightEnd = weights[weights.length - 1]?.value ?? null;

  return {
    calorieTarget,
    calorieActual: logStats?.avg_calories || 0,
    calorieRate:
      calorieTarget > 0 ? ((logStats?.avg_calories || 0) / calorieTarget) * 100 : 0,
    trainingCompleted,
    trainingTotal,
    trainingRate:
      trainingTotal > 0 ? (trainingCompleted / trainingTotal) * 100 : 0,
    avgProtein: logStats?.avg_protein || 0,
    avgCarbs: logStats?.avg_carbs || 0,
    avgFat: logStats?.avg_fat || 0,
    weightStart,
    weightEnd,
    weightChange:
      weightStart !== null && weightEnd !== null
        ? Number((weightEnd - weightStart).toFixed(1))
        : null,
  };
}

function ReportContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const reportId = searchParams.get("week");

  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [plan, setPlan] = useState<CarbonCyclePlan | null>(null);
  const [logStats, setLogStats] = useState<LogStats | null>(null);
  const [weights, setWeights] = useState<WeightChartPoint[]>([]);
  const [weightInput, setWeightInput] = useState("");
  const [showWeightModal, setShowWeightModal] = useState(false);
  const [currentReport, setCurrentReport] = useState<string>("");
  const [historicalReport, setHistoricalReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState("");

  const weeklyStats = useMemo(
    () => buildWeeklyStats(plan, logStats, weights),
    [plan, logStats, weights],
  );

  const loadCurrentWeek = useCallback(async (userId: string) => {
    const [activePlan, stats, weightHistory] = await Promise.all([
      planApi.getActive(userId).catch(() => null),
      logApi.getStats(userId, 7).catch(() => null),
      reportApi.getWeightHistory(userId).catch(() => []),
    ]);
    setPlan(activePlan);
    setLogStats(stats);
    setWeights(weightHistory);
  }, []);

  const loadHistorical = useCallback(async (targetReportId: string) => {
    const detail = await reportApi.getById(targetReportId);
    setHistoricalReport(detail);
    setCurrentReport(detail.summary || "");
  }, []);

  useEffect(() => {
    const userId = userStorage.getUserId();
    if (!userId) {
      router.push("/login");
      return;
    }

    const run = async () => {
      setLoading(true);
      setError("");
      try {
        if (reportId) {
          await loadHistorical(reportId);
        } else {
          await loadCurrentWeek(userId);
        }
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    };

    void run();
  }, [loadCurrentWeek, loadHistorical, reportId, router]);

  const handleGenerate = async () => {
    const userId = userStorage.getUserId();
    if (!userId || !weeklyStats) {
      return;
    }

    setGenerating(true);
    setError("");
    try {
      const response = await reportApi.generateWeekly({
        user_id: userId,
        plan_id: plan?.id,
        stats: weeklyStats,
      });
      setCurrentReport(response.report);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "报告生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleAddWeight = async () => {
    const userId = userStorage.getUserId();
    const value = Number(weightInput);
    if (!userId || Number.isNaN(value) || value <= 0) {
      return;
    }

    try {
      await weightApi.create({
        user_id: userId,
        date: new Date().toISOString().split("T")[0],
        weight_kg: value,
      });
      const weightHistory = await reportApi.getWeightHistory(userId).catch(() => []);
      setWeights(weightHistory);
      setWeightInput("");
      setShowWeightModal(false);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "体重保存失败");
    }
  };

  const title = historicalReport ? "历史周报" : "本周复盘";
  const displayStats = historicalReport
    ? {
        calorieRate: historicalReport.calorie_rate,
        trainingRate: historicalReport.training_rate,
        weightChange: historicalReport.weight_change,
        avgProtein: historicalReport.avg_protein,
        avgCarbs: historicalReport.avg_carbs,
        avgFat: historicalReport.avg_fat,
      }
    : weeklyStats;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-primary animate-pulse text-xl font-bold">
        正在加载报告...
      </div>
    );
  }

  return (
    <div className="max-w-[1200px] mx-auto p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-black text-primary">{title}</h1>
          <p className="text-muted-foreground mt-1">
            {historicalReport
              ? `${historicalReport.week_start} - ${historicalReport.week_end}`
              : "基于真实计划、日志、体重和 Agent 分析生成"}
          </p>
        </div>
        <div className="flex gap-3">
          {!historicalReport && (
            <button
              onClick={() => setShowWeightModal(true)}
              className="px-4 py-2 rounded-xl bg-secondary hover:bg-secondary/80 font-bold text-sm transition-colors"
            >
              记录体重
            </button>
          )}
          <button
            onClick={() => router.push(historicalReport ? "/planner" : "/")}
            className="px-4 py-2 rounded-xl bg-primary/10 hover:bg-primary/20 text-primary font-bold text-sm transition-colors"
          >
            返回
          </button>
        </div>
      </div>

      {error && (
        <GlassCard className="border border-red-200 text-red-600">{error}</GlassCard>
      )}

      <div className="grid grid-cols-4 gap-4">
        <GlassCard className="text-center">
          <div className="text-4xl font-black text-primary">
            {displayStats?.calorieRate?.toFixed(0) || 0}%
          </div>
          <div className="text-xs font-bold text-muted-foreground mt-2 uppercase">
            热量达标率
          </div>
        </GlassCard>

        <GlassCard className="text-center">
          <div className="text-4xl font-black text-accent">
            {displayStats?.trainingRate?.toFixed(0) || 0}%
          </div>
          <div className="text-xs font-bold text-muted-foreground mt-2 uppercase">
            训练完成率
          </div>
        </GlassCard>

        <GlassCard className="text-center">
          <div className="text-4xl font-black text-rose-500">
            {displayStats?.weightChange === null || displayStats?.weightChange === undefined
              ? "--"
              : `${displayStats.weightChange > 0 ? "+" : ""}${displayStats.weightChange.toFixed(1)}`}
          </div>
          <div className="text-xs font-bold text-muted-foreground mt-2 uppercase">
            体重变化 (kg)
          </div>
        </GlassCard>

        <GlassCard className="text-center">
          <div className="flex justify-center gap-3 text-sm font-bold">
            <span className="text-amber-600">
              碳 {displayStats?.avgCarbs?.toFixed(0) || 0}g
            </span>
            <span className="text-emerald-600">
              蛋 {displayStats?.avgProtein?.toFixed(0) || 0}g
            </span>
            <span className="text-rose-600">
              脂 {displayStats?.avgFat?.toFixed(0) || 0}g
            </span>
          </div>
          <div className="text-xs font-bold text-muted-foreground mt-3 uppercase">
            日均宏量
          </div>
        </GlassCard>
      </div>

      <GlassCard>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-extrabold text-primary">
            {historicalReport ? "周报详情" : "AI 分析与建议"}
          </h2>
          {!historicalReport && (
            <button
              onClick={handleGenerate}
              disabled={generating || !weeklyStats}
              className="px-4 py-2 rounded-xl bg-accent text-white font-bold text-sm hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              {generating ? "生成中..." : "生成周报"}
            </button>
          )}
        </div>

        {currentReport ? (
          <div className="prose prose-sm max-w-none whitespace-pre-wrap">
            {currentReport}
          </div>
        ) : historicalReport?.recommendations?.length ? (
          <div className="space-y-3">
            {historicalReport.recommendations.map((item) => (
              <div key={item} className="rounded-xl bg-secondary/30 p-4">
                {item}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-muted-foreground">
            点击“生成周报”获取本周 Agent 复盘建议。
          </div>
        )}
      </GlassCard>

      {showWeightModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-80 shadow-2xl">
            <h3 className="text-lg font-bold mb-4">记录今天体重</h3>
            <input
              type="number"
              step="0.1"
              value={weightInput}
              onChange={(event) => setWeightInput(event.target.value)}
              placeholder="例如 72.5"
              className="w-full px-4 py-3 rounded-xl border bg-secondary/30 text-lg font-bold text-center focus:outline-none focus:ring-2 focus:ring-primary"
              autoFocus
            />
            <div className="flex gap-3 mt-4">
              <button
                onClick={() => setShowWeightModal(false)}
                className="flex-1 py-2 rounded-xl bg-secondary font-bold"
              >
                取消
              </button>
              <button
                onClick={handleAddWeight}
                className="flex-1 py-2 rounded-xl bg-primary text-white font-bold"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReportPage() {
  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center text-primary animate-pulse text-xl font-bold">
          正在加载报告...
        </div>
      }
    >
      <ReportContent />
    </Suspense>
  );
}

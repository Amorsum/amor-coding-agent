'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Braces,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Code2,
  FileDiff,
  FlaskConical,
  GitCompareArrows,
  ListTree,
  RefreshCw,
  Route,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type ExperimentListItem = {
  id: string;
  experiment_id: string;
  dimension: string;
  provider: string;
  model: string | null;
  started_at: string;
  passed: boolean;
  repeats: number;
  task_count: number;
  strategies: string[];
  fake_provider: boolean;
};

type Variant = {
  strategy: string;
  passed: boolean;
  metrics: Record<string, unknown>;
};

type Attempt = {
  task_id: string;
  attempt: number;
  strategy: string;
  actual_status: string;
  expected_status?: string;
  outcome_matches_expected: boolean;
  rounds?: number;
  tool_calls?: number;
  total_tokens?: number;
  duration_ms?: number;
  failure_category?: string | null;
};

type ExperimentDetail = ExperimentListItem & {
  dataset_version: string;
  dataset_fingerprint: string;
  prompt_version: string;
  comparison: Record<string, unknown>;
  variants: Variant[];
  attempts: Attempt[];
};

type AttemptDetail = {
  attempt: Attempt;
  report: {
    final_status: string;
    git_diff: string;
    task?: { instruction?: string; acceptance_criteria?: string[] };
    state?: {
      phase?: string;
      plan?: Array<{ step_id: number; task: string; status: string }>;
      relevant_files?: string[];
      modified_files?: string[];
      latest_error_summary?: string | null;
      verification_attempts?: number;
      budget_overrun_tokens?: number;
    };
    verification?: {
      passed: boolean;
      failure_category?: string | null;
      checks?: Array<{ name: string; passed: boolean; summary: string }>;
    };
  };
  trace: Array<{
    event_type: string;
    phase: string;
    created_at?: string;
    payload?: Record<string, unknown>;
  }>;
};

type WebMcpDocument = Document & {
  modelContext?: {
    registerTool: (
      tool: {
        name: string;
        title: string;
        description: string;
        inputSchema: object;
        annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
        execute: (input: unknown) => unknown;
      },
      options: { signal: AbortSignal },
    ) => void | Promise<void>;
  };
};

const metricRows = [
  ['单次运行成功率', 'attempt_success_rate', 'percent'],
  ['首轮成功率', 'first_try_success_rate', 'percent'],
  ['回归率', 'regression_rate', 'percent'],
  ['平均工具调用', 'average_tool_calls', 'number'],
  ['Token 总数', 'total_tokens', 'integer'],
  ['平均读取文件', 'average_files_read', 'number'],
] as const;

export default function Home() {
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null);
  const [selectedAttempt, setSelectedAttempt] = useState<Attempt | null>(null);
  const [attemptDetail, setAttemptDetail] = useState<AttemptDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [attemptLoading, setAttemptLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExperiments = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/experiments');
      if (!response.ok) throw new Error(`API 返回 ${response.status}`);
      const payload = (await response.json()) as { items: ExperimentListItem[] };
      setExperiments(payload.items);
      setSelectedId((current) => current ?? payload.items[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取实验数据');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    fetch('/api/experiments')
      .then((response) => {
        if (!response.ok) throw new Error(`API 返回 ${response.status}`);
        return response.json() as Promise<{ items: ExperimentListItem[] }>;
      })
      .then((payload) => {
        if (!active) return;
        setExperiments(payload.items);
        setSelectedId(payload.items[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '无法读取实验数据');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const context = (document as WebMcpDocument).modelContext;
    if (!context?.registerTool || !experiments.length) return;
    const lifecycle = new AbortController();
    void Promise.resolve(
      context.registerTool(
        {
          name: 'select_amor_experiment',
          title: '选择 AMOR 实验',
          description: '在只读工作台中打开一个已列出的 AMOR 实验。',
          inputSchema: {
            type: 'object',
            properties: { experimentId: { type: 'string' } },
            required: ['experimentId'],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: true, untrustedContentHint: false },
          execute(input) {
            const experimentId =
              typeof input === 'object' && input !== null && 'experimentId' in input
                ? (input as { experimentId?: unknown }).experimentId
                : undefined;
            const match = experiments.find((item) => item.id === experimentId);
            if (!match) throw new Error('实验不存在或未被当前 Artifact API 列出');
            setExperiment(null);
            setSelectedAttempt(null);
            setAttemptDetail(null);
            setSelectedId(match.id);
            return { selected: match.experiment_id, dimension: match.dimension };
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch(() => undefined);
    return () => lifecycle.abort();
  }, [experiments]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    fetch(`/api/experiments/${selectedId}`)
      .then((response) => {
        if (!response.ok) throw new Error(`实验详情返回 ${response.status}`);
        return response.json() as Promise<ExperimentDetail>;
      })
      .then((payload) => {
        if (!active) return;
        setExperiment(payload);
        setAttemptLoading(Boolean(payload.attempts[0]));
        setSelectedAttempt(payload.attempts[0] ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '无法读取实验详情');
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId || !selectedAttempt) return;
    let active = true;
    fetch(
      `/api/experiments/${selectedId}/attempts/${encodeURIComponent(selectedAttempt.strategy)}/${encodeURIComponent(selectedAttempt.task_id)}/${selectedAttempt.attempt}`,
    )
      .then((response) => {
        if (!response.ok) throw new Error(`任务详情返回 ${response.status}`);
        return response.json() as Promise<AttemptDetail>;
      })
      .then((payload) => {
        if (active) setAttemptDetail(payload);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : '无法读取任务详情');
      })
      .finally(() => {
        if (active) setAttemptLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedAttempt, selectedId]);

  const selectedSummary = useMemo(
    () => experiments.find((item) => item.id === selectedId) ?? null,
    [experiments, selectedId],
  );

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="app-header">
        <div className="flex items-center gap-3">
          <div className="amor-mark" aria-hidden="true">A</div>
          <div>
            <div className="flex items-baseline gap-2">
              <h1 className="text-base font-semibold tracking-[0.16em]">AMOR</h1>
              <span className="text-xs text-muted-foreground">v0.7.0</span>
            </div>
            <p className="text-xs text-muted-foreground">Agent 可观测工作台</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
            <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_12px_rgb(52_211_153/70%)]" />
            本地只读模式
          </span>
          <Button variant="outline" size="sm" onClick={() => void loadExperiments()}>
            <RefreshCw data-icon="inline-start" />刷新
          </Button>
        </div>
      </header>

      <div className="workbench-grid">
        <aside className="experiment-rail">
          <div className="section-kicker">
            <FlaskConical className="size-3.5" />实验运行
            <Badge variant="outline" className="ml-auto">{experiments.length}</Badge>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-2 pr-3">
              {loading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-24 w-full bg-white/6" />
                ))
              ) : experiments.length ? (
                experiments.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      setExperiment(null);
                      setSelectedAttempt(null);
                      setAttemptDetail(null);
                      setSelectedId(item.id);
                    }}
                    className="experiment-button"
                    data-active={item.id === selectedId}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-foreground">{item.experiment_id}</span>
                      <ChevronRight className="size-3.5 text-muted-foreground" />
                    </span>
                    <span className="mt-3 flex items-center gap-2">
                      <Badge variant={item.fake_provider ? 'outline' : 'secondary'}>
                        {item.provider}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {dimensionLabel(item.dimension)} · {item.task_count} 任务
                      </span>
                    </span>
                    <span className="mt-2 block text-left text-xs text-muted-foreground">
                      {formatDate(item.started_at)}
                    </span>
                  </button>
                ))
              ) : (
                <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
                  暂无实验产物
                </p>
              )}
            </div>
          </ScrollArea>
          <div className="rail-note">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-cyan-300" />
            <p>仅展示服务器发现的 Artifact，不接受任意文件路径。</p>
          </div>
        </aside>

        <section className="analysis-pane">
          {error ? (
            <Empty className="min-h-[28rem] border border-rose-400/20 bg-rose-400/5">
              <EmptyHeader>
                <EmptyMedia variant="icon"><CircleAlert /></EmptyMedia>
                <EmptyTitle>无法加载 Artifact</EmptyTitle>
                <EmptyDescription>{error}</EmptyDescription>
              </EmptyHeader>
              <Button variant="outline" onClick={() => void loadExperiments()}>重试</Button>
            </Empty>
          ) : !selectedSummary || !experiment ? (
            <DashboardSkeleton hasExperiments={experiments.length > 0} />
          ) : (
            <>
              <div className="experiment-heading">
                <div>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge className="bg-cyan-300 text-slate-950 hover:bg-cyan-300">
                      {dimensionLabel(experiment.dimension)}
                    </Badge>
                    <Badge variant={selectedSummary.passed ? 'secondary' : 'destructive'}>
                      {selectedSummary.passed ? '管道通过' : '存在失败'}
                    </Badge>
                    {selectedSummary.fake_provider && (
                      <Badge variant="outline" className="border-amber-300/40 text-amber-200">
                        Fake · 非模型质量证据
                      </Badge>
                    )}
                  </div>
                  <h2 className="font-mono text-xl font-semibold tracking-tight sm:text-2xl">
                    {experiment.experiment_id}
                  </h2>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {experiment.dataset_version} · {experiment.provider}/{experiment.model ?? '无模型'} · 重复 {experiment.repeats} 次
                  </p>
                </div>
                <div className="fingerprint-card">
                  <span>DATASET FINGERPRINT</span>
                  <code>{experiment.dataset_fingerprint.slice(0, 20)}…</code>
                </div>
              </div>

              <ComparisonCards experiment={experiment} />

              <Card className="border-white/8 bg-card/70">
                <CardHeader className="border-b border-white/7">
                  <CardTitle className="flex items-center gap-2">
                    <GitCompareArrows className="size-4 text-cyan-300" />策略指标对比
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-0">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-white/7 hover:bg-transparent">
                        <TableHead className="pl-4 text-muted-foreground">指标</TableHead>
                        {experiment.variants.map((variant) => (
                          <TableHead key={variant.strategy} className="font-mono text-cyan-100">
                            {variant.strategy}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {metricRows.map(([label, key, format]) => (
                        <TableRow key={key} className="border-white/7">
                          <TableCell className="pl-4 text-muted-foreground">{label}</TableCell>
                          {experiment.variants.map((variant) => (
                            <TableCell key={variant.strategy} className="font-mono">
                              {formatMetric(variant.metrics[key], format)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <Card className="min-h-0 border-white/8 bg-card/70">
                <CardHeader className="border-b border-white/7">
                  <CardTitle className="flex items-center gap-2">
                    <ListTree className="size-4 text-cyan-300" />任务与 Attempt
                    <Badge variant="outline" className="ml-auto">{experiment.attempts.length}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="max-h-[28rem] overflow-auto px-0">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-card">
                      <TableRow className="border-white/7 hover:bg-transparent">
                        <TableHead className="pl-4">任务</TableHead>
                        <TableHead>策略</TableHead>
                        <TableHead>状态</TableHead>
                        <TableHead className="text-right">轮次</TableHead>
                        <TableHead className="text-right">工具</TableHead>
                        <TableHead className="pr-4 text-right">Token</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {experiment.attempts.map((item) => {
                        const active = attemptKey(item) === (selectedAttempt ? attemptKey(selectedAttempt) : '');
                        return (
                          <TableRow
                            key={attemptKey(item)}
                            data-state={active ? 'selected' : undefined}
                            className="border-white/7"
                          >
                            <TableCell className="max-w-56 pl-4 font-mono text-xs">
                              <button
                                type="button"
                                className="block max-w-full truncate text-left text-cyan-50 underline-offset-4 hover:text-cyan-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/50"
                                onClick={() => {
                                  setAttemptDetail(null);
                                  setAttemptLoading(true);
                                  setSelectedAttempt(item);
                                }}
                              >
                                {item.task_id}
                              </button>
                            </TableCell>
                            <TableCell><Badge variant="outline">{item.strategy}</Badge></TableCell>
                            <TableCell><StatusBadge status={item.actual_status} /></TableCell>
                            <TableCell className="text-right font-mono">{item.rounds ?? '—'}</TableCell>
                            <TableCell className="text-right font-mono">{item.tool_calls ?? '—'}</TableCell>
                            <TableCell className="pr-4 text-right font-mono">{item.total_tokens ?? '—'}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </>
          )}
        </section>

        <aside className="evidence-pane">
          <div className="section-kicker border-b border-white/7 px-5 py-4">
            <TerminalSquare className="size-3.5" />执行证据
          </div>
          {attemptLoading ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-7 w-2/3 bg-white/6" />
              <Skeleton className="h-28 w-full bg-white/6" />
              <Skeleton className="h-64 w-full bg-white/6" />
            </div>
          ) : attemptDetail ? (
            <EvidencePanel detail={attemptDetail} />
          ) : (
            <Empty className="h-[70vh] border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon"><Route /></EmptyMedia>
                <EmptyTitle>选择一个任务</EmptyTitle>
                <EmptyDescription>这里会显示 Verifier 结果、状态轨迹与 Git Diff。</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </aside>
      </div>
    </main>
  );
}

function ComparisonCards({ experiment }: { experiment: ExperimentDetail }) {
  const items = [
    ['成功率差值', 'success_rate_delta', Activity],
    ['输入 Token 降低', 'input_token_reduction_rate', Braces],
    ['工具调用降低', 'tool_call_reduction_rate', TerminalSquare],
    ['上下文字符降低', 'context_char_reduction_rate', Code2],
  ] as const;
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map(([label, key, Icon]) => {
        const value = numeric(experiment.comparison[key]);
        return (
          <Card key={key} size="sm" className="metric-card">
            <CardContent>
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="text-xs">{label}</span>
                <Icon className="size-4 text-cyan-300" />
              </div>
              <p className="mt-3 font-mono text-2xl font-semibold tracking-tight">
                {value === null ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`}
              </p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function EvidencePanel({ detail }: { detail: AttemptDetail }) {
  const report = detail.report;
  const checks = report.verification?.checks ?? [];
  return (
    <Tabs defaultValue="summary" className="h-[calc(100vh-7.5rem)] min-h-[38rem]">
      <div className="px-5 pt-4">
        <p className="truncate font-mono text-sm font-medium">{detail.attempt.task_id}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge status={report.final_status} />
          <Badge variant="outline">{detail.attempt.strategy}</Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <Clock3 className="size-3" />{formatDuration(detail.attempt.duration_ms)}
          </span>
        </div>
        <TabsList variant="line" className="mt-5 w-full justify-start border-b border-white/7">
          <TabsTrigger value="summary">验证</TabsTrigger>
          <TabsTrigger value="trace">轨迹 · {detail.trace.length}</TabsTrigger>
          <TabsTrigger value="diff">Diff</TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="summary" className="min-h-0">
        <ScrollArea className="h-full px-5 pb-6">
          {report.task?.instruction && (
            <section className="evidence-section">
              <h3>任务说明</h3>
              <p>{report.task.instruction}</p>
            </section>
          )}
          {!report.verification?.passed && (
            <section className="evidence-section">
              <h3>运行结论</h3>
              <div className="rounded-lg border border-rose-400/20 bg-rose-400/[0.06] p-3 text-xs leading-relaxed text-rose-100/85">
                {failureSummary(report)}
              </div>
            </section>
          )}
          <section className="evidence-section">
            <h3>Verifier 检查</h3>
            <div className="space-y-2">
              {checks.map((check) => (
                <div key={check.name} className="check-row">
                  <span className={check.passed ? 'check-icon pass' : 'check-icon fail'}>
                    {check.passed ? <Check /> : <CircleAlert />}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs text-foreground">{checkLabel(check.name)}</p>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{check.summary}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
          {!!report.state?.plan?.length && (
            <section className="evidence-section">
              <h3>结构化计划</h3>
              <ol className="space-y-2">
                {report.state.plan.map((step) => (
                  <li key={step.step_id} className="plan-row">
                    <span>{String(step.step_id).padStart(2, '0')}</span>
                    <p>{step.task}</p>
                    <Badge variant="outline">{step.status}</Badge>
                  </li>
                ))}
              </ol>
            </section>
          )}
          <section className="evidence-section">
            <h3>文件证据</h3>
            <div className="grid grid-cols-2 gap-3">
              <FileCount label="已读取" value={report.state?.relevant_files?.length ?? 0} />
              <FileCount label="已修改" value={report.state?.modified_files?.length ?? 0} />
            </div>
          </section>
        </ScrollArea>
      </TabsContent>

      <TabsContent value="trace" className="min-h-0">
        <ScrollArea className="h-full px-5 pb-6">
          <div className="trace-line">
            {detail.trace.map((event, index) => (
              <div key={`${event.created_at}-${index}`} className="trace-event">
                <span className="trace-dot" />
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <code>{event.event_type}</code>
                    <Badge variant="outline">{event.phase}</Badge>
                  </div>
                  <p>{traceSummary(event.payload)}</p>
                  <time>{formatTime(event.created_at)}</time>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </TabsContent>

      <TabsContent value="diff" className="min-h-0">
        <ScrollArea className="h-full px-5 pb-6">
          {report.git_diff ? (
            <pre className="diff-block"><code>{report.git_diff}</code></pre>
          ) : (
            <Empty className="mt-8 border border-dashed border-white/10">
              <EmptyHeader>
                <EmptyMedia variant="icon"><FileDiff /></EmptyMedia>
                <EmptyTitle>没有代码差异</EmptyTitle>
                <EmptyDescription>安全阻断任务应当保持空 Diff。</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </ScrollArea>
      </TabsContent>
    </Tabs>
  );
}

function StatusBadge({ status }: { status: string }) {
  const succeeded = status === 'SUCCEEDED';
  const blocked = status === 'BLOCKED';
  return (
    <Badge
      variant="outline"
      className={
        succeeded
          ? 'border-emerald-400/35 bg-emerald-400/10 text-emerald-300'
          : blocked
            ? 'border-amber-300/35 bg-amber-300/10 text-amber-200'
            : 'border-rose-400/35 bg-rose-400/10 text-rose-300'
      }
    >
      {statusLabel(status)}
    </Badge>
  );
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    SUCCEEDED: '验收通过',
    FAILED: '验收失败',
    BLOCKED: '安全阻断',
    BUDGET_EXHAUSTED: '预算耗尽',
    CANCELLED: '已取消',
  };
  return labels[status] ?? status;
}

function checkLabel(name: string) {
  const labels: Record<string, string> = {
    agent_loop: 'Agent 执行流程',
    scope: '修改范围',
    static_compile: '静态编译',
    hidden_tests: '隐藏验收测试',
  };
  if (name.startsWith('visible_tests_')) return `可见测试 ${name.slice('visible_tests_'.length)}`;
  return labels[name] ?? name;
}

function failureSummary(report: AttemptDetail['report']) {
  const state = report.state;
  if (report.final_status === 'BUDGET_EXHAUSTED') {
    const overrun = state?.budget_overrun_tokens ?? 0;
    return overrun > 0
      ? `模型总 Token 预算已耗尽，并在最后一轮超出 ${formatMetric(overrun, 'integer')} Token；当前修改未完成最终验收。`
      : '模型总 Token、时间或轮次预算已耗尽；当前修改未完成最终验收。';
  }
  if (state?.latest_error_summary) return state.latest_error_summary;
  return report.verification?.failure_category
    ? `独立验收未通过：${report.verification.failure_category}`
    : '独立验收未通过，请展开下方检查项查看原因。';
}

function FileCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.025] p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-xl">{value}</p>
    </div>
  );
}

function DashboardSkeleton({ hasExperiments }: { hasExperiments: boolean }) {
  return (
    <div className="space-y-4">
      <div className="space-y-3 py-4">
        <Skeleton className="h-5 w-32 bg-white/6" />
        <Skeleton className="h-9 w-2/3 bg-white/6" />
        <Skeleton className="h-4 w-1/2 bg-white/6" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 bg-white/6" />)}
      </div>
      {!hasExperiments && (
        <p className="pt-8 text-sm text-muted-foreground">运行一次 `amor experiment` 后，结果会自动显示在这里。</p>
      )}
    </div>
  );
}

function numeric(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

function formatMetric(value: unknown, format: 'percent' | 'number' | 'integer'): string {
  const number = numeric(value);
  if (number === null) return '未测量';
  if (format === 'percent') return `${(number * 100).toFixed(1)}%`;
  if (format === 'integer') return Math.round(number).toLocaleString('zh-CN');
  return number.toFixed(2);
}

function dimensionLabel(value: string): string {
  return value === 'planning' ? '规划策略实验' : '上下文策略实验';
}

function attemptKey(attempt: Attempt): string {
  return `${attempt.strategy}:${attempt.task_id}:${attempt.attempt}`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

function formatTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

function formatDuration(value?: number): string {
  if (typeof value !== 'number') return '未记录';
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
}

function traceSummary(payload?: Record<string, unknown>): string {
  if (!payload) return '已记录事件';
  if (typeof payload.reason === 'string') return payload.reason;
  if (typeof payload.summary === 'string') return payload.summary;
  if (typeof payload.tool === 'string') return `调用 ${payload.tool}`;
  if (Array.isArray(payload.tool_names)) return `工具：${payload.tool_names.join(', ')}`;
  return '结构化事件已记录';
}

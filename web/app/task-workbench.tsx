'use client';

import { useEffect, useState } from 'react';
import {
  Activity,
  Check,
  CircleAlert,
  ClipboardCheck,
  Code2,
  Container,
  FileDiff,
  FolderGit2,
  GitBranch,
  GitCommitHorizontal,
  History,
  KeyRound,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  PencilLine,
  PackageCheck,
  Play,
  Plus,
  Send,
  ShieldCheck,
  Square,
  X,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type ProviderName = 'openai-responses' | 'deepseek-responses';

type RuntimeInfo = {
  mode: string;
  max_concurrent_jobs: number;
  working_directory?: string;
  providers: Record<ProviderName, boolean>;
  docker: {
    cli_available: boolean;
    engine_available: boolean;
    image_available: boolean;
    image: string;
    reason?: string | null;
  };
};

type PythonCase = {
  name: string;
  module: string;
  callable: string;
  args_json: string;
  kwargs_json: string;
  expectation: 'equals' | 'raises';
  expected_json: string;
  exception_type: string;
  rationale: string;
};

type AcceptancePlan = {
  status: 'READY' | 'NEEDS_INPUT';
  plan_id: string;
  baseline_commit: string;
  instruction: string;
  acceptance_criteria: string[];
  preserved_behaviors: string[];
  edge_cases: string[];
  allowed_paths: string[];
  validation_commands: string[][];
  python_cases: PythonCase[];
  evidence_files: string[];
  questions: string[];
  summary: string;
  provider: string;
  model: string;
  token_usage: Record<string, number>;
  contract_sha256: string;
};

type VerificationCheck = { name: string; passed: boolean; summary: string; duration_ms?: number };

type RunResult = {
  run_id: string;
  final_status: string;
  task?: {
    sandbox?: {
      mode: 'host' | 'docker';
      image: string;
      cpus: number;
      memory_mb: number;
      pids_limit: number;
      tmpfs_mb: number;
      workspace_growth_mb: number;
      network_disabled: boolean;
    };
  };
  git_diff: string;
  state: {
    phase: string;
    round: number;
    token_usage: Record<string, number>;
    relevant_files: string[];
    modified_files: string[];
    verification_attempts: number;
    latest_error_summary?: string | null;
    plan?: Array<{ step_id: number; task: string; status: string }>;
  };
  verification: {
    passed: boolean;
    failure_category?: string | null;
    checks: VerificationCheck[];
  };
  finished_at: string;
};

type DeliveryState = {
  attempt: number;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
  request: {
    branch_name: string;
    commit_requested: boolean;
    commit_message: string;
    patch_sha256: string;
  };
  report: {
    delivery_id: string;
    status: string;
    branch_name: string;
    baseline_commit: string;
    patch_sha256: string;
    commit_requested: boolean;
    commit_sha?: string | null;
    verification?: { passed: boolean; checks: VerificationCheck[] } | null;
    error?: string | null;
  } | null;
  report_artifact: string | null;
  workspace_artifact: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

type JobEvent = {
  sequence: number;
  created_at: string;
  kind: string;
  phase: string;
  message: string;
  payload: Record<string, unknown>;
};

type ClarificationAnswer = { question: string; answer: string };

type ContractRevision = {
  revision: number;
  source: 'planner' | 'clarification' | 'manual';
  contract_sha256: string;
  artifact: string;
  note: string;
  created_at: string;
};

type Job = {
  job_id: string;
  status: string;
  phase: string;
  planning_request: {
    repository: string;
    instruction: string;
    acceptance_criteria: string[];
    allowed_paths: string[];
    validation_commands: string[][];
    provider: ProviderName;
    model: string;
  };
  plan: AcceptancePlan | null;
  run: RunResult | null;
  error: string | null;
  clarifications: Array<{
    based_on_sha256: string;
    answers: ClarificationAnswer[];
    created_at: string;
  }>;
  contract_revisions: ContractRevision[];
  patch_sha256: string | null;
  deliveries: DeliveryState[];
  events: JobEvent[];
  created_at: string;
  updated_at: string;
};

type TaskForm = {
  repository: string;
  instruction: string;
  criteria: string;
  allowedPaths: string;
  validationCommands: string;
  provider: ProviderName;
  model: string;
  maxTokens: string;
  confirm: boolean;
};

const initialForm: TaskForm = {
  repository: '',
  instruction: '',
  criteria: '',
  allowedPaths: 'src/**\ntests/**',
  validationCommands: '',
  provider: 'openai-responses',
  model: '',
  maxTokens: '40000',
  confirm: false,
};

const activeStatuses = new Set([
  'QUEUED',
  'PLANNING',
  'REPLANNING',
  'EXECUTION_QUEUED',
  'RUNNING',
  'DELIVERY_QUEUED',
  'DELIVERING',
  'CANCEL_REQUESTED',
]);

export function TaskWorkbench() {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [creating, setCreating] = useState(true);
  const [form, setForm] = useState<TaskForm>(initialForm);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = async (preferredId?: string) => {
    const payload = await api<{ items: Job[] }>('/api/jobs');
    setJobs(payload.items);
    const nextId = preferredId ?? selectedId ?? payload.items[0]?.job_id ?? null;
    setSelectedId(nextId);
    return nextId;
  };

  useEffect(() => {
    let active = true;
    Promise.all([api<RuntimeInfo>('/api/runtime'), api<{ items: Job[] }>('/api/jobs')])
      .then(([runtimePayload, jobsPayload]) => {
        if (!active) return;
        setRuntime(runtimePayload);
        setJobs(jobsPayload.items);
        setForm((current) => ({
          ...current,
          repository: current.repository || runtimePayload.working_directory || '',
          provider:
            runtimePayload.providers['openai-responses'] ||
            !runtimePayload.providers['deepseek-responses']
              ? 'openai-responses'
              : 'deepseek-responses',
        }));
        if (jobsPayload.items[0]) {
          setSelectedId(jobsPayload.items[0].job_id);
          setCreating(false);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(errorMessage(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId || creating) return;
    let active = true;
    api<Job>(`/api/jobs/${selectedId}`)
      .then((detail) => {
        if (!active) return;
        setJob(detail);
        setJobs((current) => {
          const summary = { ...detail, events: [] };
          return [summary, ...current.filter((item) => item.job_id !== detail.job_id)].sort(
            (a, b) => b.created_at.localeCompare(a.created_at),
          );
        });
      })
      .catch((reason: unknown) => {
        if (active) setError(errorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [selectedId, creating]);

  const streamingJobId = job?.job_id;
  const streamingStatus = job?.status;
  const streamingSequence = job?.events.at(-1)?.sequence ?? 0;
  useEffect(() => {
    if (!streamingJobId || !streamingStatus || !activeStatuses.has(streamingStatus)) return;
    const stream = new EventSource(`/api/jobs/${streamingJobId}/events?after=${streamingSequence}`);
    const refresh = () => {
      void api<Job>(`/api/jobs/${streamingJobId}`)
        .then((detail) => {
          setJob(detail);
          setJobs((current) => {
            const summary = { ...detail, events: [] };
            return [summary, ...current.filter((item) => item.job_id !== detail.job_id)].sort(
              (a, b) => b.created_at.localeCompare(a.created_at),
            );
          });
        })
        .catch((reason: unknown) => setError(errorMessage(reason)));
    };
    stream.addEventListener('job', refresh);
    stream.addEventListener('settled', () => {
      refresh();
      stream.close();
    });
    stream.onerror = () => stream.close();
    return () => stream.close();
  }, [streamingJobId, streamingSequence, streamingStatus]);

  const createJob = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const validationCommands = parseCommands(form.validationCommands);
      const created = await api<Job>('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repository: form.repository.trim(),
          instruction: form.instruction.trim(),
          acceptance_criteria: lines(form.criteria),
          allowed_paths: lines(form.allowedPaths),
          validation_commands: validationCommands,
          provider: form.provider,
          model: form.model.trim(),
          max_tokens: Number(form.maxTokens),
          confirm_send_code: form.confirm,
        }),
      });
      await loadJobs(created.job_id);
      setSelectedId(created.job_id);
      setJob(created);
      setCreating(false);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const cancelJob = async () => {
    if (!job) return;
    setSubmitting(true);
    try {
      const updated = await api<Job>(`/api/jobs/${job.job_id}/cancel`, { method: 'POST' });
      setJob(updated);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const selectJob = (jobId: string) => {
    setCreating(false);
    setSelectedId(jobId);
  };

  return (
    <div className="task-workbench-grid">
      <aside className="task-rail">
        <Button
          className="w-full bg-cyan-300 text-slate-950 hover:bg-cyan-200"
          onClick={() => {
            setCreating(true);
            setSelectedId(null);
            setJob(null);
            setError(null);
          }}
        >
          <Plus data-icon="inline-start" />创建真实任务
        </Button>
        <div className="section-kicker mt-6">
          <Activity className="size-3.5" />最近任务
          <Badge variant="outline" className="ml-auto">{jobs.length}</Badge>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-2 pr-3">
            {loading ? (
              Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-24 bg-white/6" />
              ))
            ) : jobs.length ? (
              jobs.map((item) => (
                <button
                  key={item.job_id}
                  type="button"
                  className="job-button"
                  data-active={!creating && item.job_id === selectedId}
                  onClick={() => selectJob(item.job_id)}
                >
                  <span className="line-clamp-2 text-sm leading-snug text-foreground/90">
                    {item.planning_request.instruction}
                  </span>
                  <span className="mt-3 flex items-center justify-between gap-2">
                    <JobStatusBadge status={item.status} />
                    <time className="font-mono text-[0.68rem] text-muted-foreground">
                      {formatTime(item.updated_at)}
                    </time>
                  </span>
                </button>
              ))
            ) : (
              <p className="rounded-lg border border-dashed border-white/10 p-4 text-sm text-muted-foreground">
                尚未创建真实任务
              </p>
            )}
          </div>
        </ScrollArea>
        <div className="rail-note">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-cyan-300" />
          <p>任务串行执行。只有再次确认后才会在独立交付 worktree 中创建本地分支；不会自动推送。</p>
        </div>
      </aside>

      <section className="task-main">
        {error && (
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-rose-400/25 bg-rose-400/[0.07] p-4 text-sm text-rose-100">
            <CircleAlert className="mt-0.5 size-4 shrink-0" />
            <p className="min-w-0 flex-1 break-words">{error}</p>
            <button type="button" aria-label="关闭错误" onClick={() => setError(null)}>×</button>
          </div>
        )}

        {creating ? (
          <TaskCreationForm
            form={form}
            runtime={runtime}
            submitting={submitting}
            onChange={setForm}
            onSubmit={createJob}
          />
        ) : !job ? (
          <div className="space-y-4">
            <Skeleton className="h-24 bg-white/6" />
            <Skeleton className="h-96 bg-white/6" />
          </div>
        ) : (
          <JobDetail
            job={job}
            runtime={runtime}
            submitting={submitting}
            onCancel={() => void cancelJob()}
            onUpdated={(updated) => {
              setJob(updated);
              void loadJobs(updated.job_id);
            }}
            onError={(reason) => setError(errorMessage(reason))}
          />
        )}
      </section>
    </div>
  );
}

function TaskCreationForm({
  form,
  runtime,
  submitting,
  onChange,
  onSubmit,
}: {
  form: TaskForm;
  runtime: RuntimeInfo | null;
  submitting: boolean;
  onChange: (form: TaskForm) => void;
  onSubmit: () => void;
}) {
  const configured = runtime?.providers[form.provider] ?? false;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="mx-auto max-w-5xl space-y-5"
    >
      <div className="flex flex-col justify-between gap-3 border-b border-white/8 pb-5 sm:flex-row sm:items-end">
        <div>
          <div className="section-kicker mb-2"><Plus className="size-3.5" />新任务</div>
          <h2 className="text-2xl font-semibold tracking-tight">先定义任务，再冻结验收标准</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            独立规划器只读分析仓库；你审批契约后，执行 Agent 才会开始修改代码。
          </p>
        </div>
        <Badge
          variant="outline"
          className={configured ? 'border-emerald-400/30 text-emerald-300' : 'border-amber-300/30 text-amber-200'}
        >
          <KeyRound className="size-3" />{configured ? '服务端 Key 已配置' : '服务端 Key 未配置'}
        </Badge>
      </div>

      <Card className="border-white/8 bg-card/75">
        <CardHeader><CardTitle className="flex items-center gap-2"><FolderGit2 className="size-4 text-cyan-300" />仓库与任务</CardTitle></CardHeader>
        <CardContent className="grid gap-5">
          <Field label="本地 Git 仓库绝对路径" hint="仓库必须已提交且工作区干净。">
            <input
              className="task-input font-mono"
              value={form.repository}
              onChange={(event) => onChange({ ...form, repository: event.target.value })}
              placeholder="D:\projects\example"
              required
            />
          </Field>
          <Field label="要完成的任务">
            <textarea
              className="task-input min-h-28 resize-y"
              value={form.instruction}
              onChange={(event) => onChange({ ...form, instruction: event.target.value })}
              placeholder="例如：修复空列表输入导致的异常，并保持非空输入行为不变"
              required
            />
          </Field>
          <div className="grid gap-5 lg:grid-cols-2">
            <Field label="已知验收条件" hint="每行一项；规划器会基于源码和测试补充。">
              <textarea
                className="task-input min-h-32 resize-y"
                value={form.criteria}
                onChange={(event) => onChange({ ...form, criteria: event.target.value })}
                placeholder={'空列表返回 0.0\n现有测试保持通过'}
              />
            </Field>
            <Field label="允许修改的路径" hint="每行一个 glob，不能为空。">
              <textarea
                className="task-input min-h-32 resize-y font-mono"
                value={form.allowedPaths}
                onChange={(event) => onChange({ ...form, allowedPaths: event.target.value })}
                required
              />
            </Field>
          </div>
          <Field label="验证命令" hint="每行一个 JSON 参数数组；留空时使用仓库自动建议。">
            <textarea
              className="task-input min-h-24 resize-y font-mono"
              value={form.validationCommands}
              onChange={(event) => onChange({ ...form, validationCommands: event.target.value })}
              placeholder={'["python","-m","pytest"]'}
            />
          </Field>
        </CardContent>
      </Card>

      <Card className="border-white/8 bg-card/75">
        <CardHeader><CardTitle className="flex items-center gap-2"><Code2 className="size-4 text-cyan-300" />规划模型</CardTitle></CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-[1fr_1.5fr_0.8fr]">
          <Field label="Provider">
            <select
              className="task-input"
              value={form.provider}
              onChange={(event) => onChange({ ...form, provider: event.target.value as ProviderName })}
            >
              <option value="openai-responses">OpenAI Responses</option>
              <option value="deepseek-responses">DeepSeek Responses</option>
            </select>
          </Field>
          <Field label="模型 ID">
            <input
              className="task-input font-mono"
              value={form.model}
              onChange={(event) => onChange({ ...form, model: event.target.value })}
              placeholder="填写 Provider 支持的准确模型 ID"
              required
            />
          </Field>
          <Field label="规划 Token 上限">
            <input
              className="task-input font-mono"
              type="number"
              min="1"
              max="2000000"
              value={form.maxTokens}
              onChange={(event) => onChange({ ...form, maxTokens: event.target.value })}
              required
            />
          </Field>
        </CardContent>
      </Card>

      <label className="consent-row">
        <input
          type="checkbox"
          checked={form.confirm}
          onChange={(event) => onChange({ ...form, confirm: event.target.checked })}
        />
        <span>
          我确认相关代码片段和测试输出可以发送给所选模型服务。API Key 仅由本地服务端环境变量读取。
        </span>
      </label>

      <div className="flex justify-end">
        <Button
          type="submit"
          size="lg"
          disabled={submitting || !form.confirm || !configured}
          className="bg-cyan-300 text-slate-950 hover:bg-cyan-200"
        >
          {submitting ? <LoaderCircle className="animate-spin" /> : <Send />}
          启动只读验收规划
        </Button>
      </div>
    </form>
  );
}

function JobDetail({
  job,
  runtime,
  submitting,
  onCancel,
  onUpdated,
  onError,
}: {
  job: Job;
  runtime: RuntimeInfo | null;
  submitting: boolean;
  onCancel: () => void;
  onUpdated: (job: Job) => void;
  onError: (reason: unknown) => void;
}) {
  const canCancel = activeStatuses.has(job.status) || job.status === 'AWAITING_APPROVAL';
  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="job-heading">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} />
            <Badge variant="outline" className="font-mono">{job.phase}</Badge>
            <span className="text-xs text-muted-foreground">{job.planning_request.provider} / {job.planning_request.model}</span>
          </div>
          <h2 className="text-xl font-semibold leading-snug sm:text-2xl">{job.planning_request.instruction}</h2>
          <p className="mt-2 truncate font-mono text-xs text-muted-foreground">{job.planning_request.repository}</p>
        </div>
        {canCancel && (
          <Button variant="outline" onClick={onCancel} disabled={submitting || job.status === 'CANCEL_REQUESTED'}>
            <Square data-icon="inline-start" />{job.status === 'CANCEL_REQUESTED' ? '正在取消' : '取消任务'}
          </Button>
        )}
      </div>

      {job.error && (
        <div className="rounded-lg border border-rose-400/25 bg-rose-400/[0.07] p-4 text-sm text-rose-100">
          {job.error}
        </div>
      )}

      {job.status === 'AWAITING_APPROVAL' && job.plan ? (
        <ContractReview key={job.plan.contract_sha256} job={job} plan={job.plan} runtime={runtime} onUpdated={onUpdated} onError={onError} />
      ) : job.status === 'NEEDS_INPUT' && job.plan ? (
        <NeedsInput key={job.plan.contract_sha256} job={job} plan={job.plan} runtime={runtime} onUpdated={onUpdated} onError={onError} />
      ) : job.run ? (
        <RunEvidence job={job} run={job.run} onUpdated={onUpdated} onError={onError} />
      ) : (
        <LiveProgress job={job} />
      )}
    </div>
  );
}

function ContractReview({
  job,
  plan,
  runtime,
  onUpdated,
  onError,
}: {
  job: Job;
  plan: AcceptancePlan;
  runtime: RuntimeInfo | null;
  onUpdated: (job: Job) => void;
  onError: (reason: unknown) => void;
}) {
  const [provider, setProvider] = useState<ProviderName>(job.planning_request.provider);
  const [model, setModel] = useState(job.planning_request.model);
  const [maxTokens, setMaxTokens] = useState('100000');
  const [maxSeconds, setMaxSeconds] = useState('900');
  const [retries, setRetries] = useState('2');
  const [sandboxMode, setSandboxMode] = useState<'docker' | 'host'>('docker');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState(false);
  const providerConfigured = runtime?.providers[provider] ?? false;
  const dockerReady = Boolean(runtime?.docker.engine_available && runtime?.docker.image_available);
  const sandboxReady = sandboxMode === 'host' || dockerReady;

  const approve = async () => {
    setSubmitting(true);
    try {
      const updated = await api<Job>(`/api/jobs/${job.job_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contract_sha256: plan.contract_sha256,
          provider,
          model: model.trim(),
          max_tokens: Number(maxTokens),
          max_seconds: Number(maxSeconds),
          max_verification_retries: Number(retries),
          sandbox: {
            mode: sandboxMode,
            image: runtime?.docker.image ?? 'python:3.12-slim',
            cpus: 1,
            memory_mb: 512,
            pids_limit: 128,
            tmpfs_mb: 64,
            workspace_growth_mb: 256,
            network_disabled: true,
          },
          confirm_send_code: confirmed,
        }),
      });
      onUpdated(updated);
    } catch (reason) {
      onError(reason);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <Card className="border-cyan-300/18 bg-card/75">
        <CardHeader className="border-b border-white/7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2"><ClipboardCheck className="size-4 text-cyan-300" />审阅验收契约</CardTitle>
            {!editing && (
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <PencilLine data-icon="inline-start" />编辑并生成新版本
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-6 pt-5">
          {editing ? (
            <ContractEditor
              job={job}
              plan={plan}
              onSaved={onUpdated}
              onCancel={() => setEditing(false)}
              onError={onError}
            />
          ) : (
            <ContractContents plan={plan} />
          )}
          <RevisionHistory revisions={job.contract_revisions} currentSha={plan.contract_sha256} />
        </CardContent>
      </Card>

      <Card className="h-fit border-white/8 bg-card/75 xl:sticky xl:top-[5.5rem]">
        <CardHeader><CardTitle className="flex items-center gap-2"><Play className="size-4 text-cyan-300" />执行设置</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <Field label="执行 Provider">
            <select className="task-input" value={provider} onChange={(event) => setProvider(event.target.value as ProviderName)}>
              <option value="openai-responses">OpenAI Responses</option>
              <option value="deepseek-responses">DeepSeek Responses</option>
            </select>
          </Field>
          <p className={providerConfigured ? 'text-xs text-emerald-300' : 'text-xs text-amber-200'}>
            {providerConfigured ? '所选 Provider 的服务端 Key 已配置' : '所选 Provider 的服务端 Key 未配置'}
          </p>
          <Field label="执行模型 ID">
            <input className="task-input font-mono" value={model} onChange={(event) => setModel(event.target.value)} required />
          </Field>
          <Field label="Token 上限">
            <input className="task-input font-mono" type="number" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="最长秒数">
              <input className="task-input font-mono" type="number" value={maxSeconds} onChange={(event) => setMaxSeconds(event.target.value)} />
            </Field>
            <Field label="修复重试">
              <input className="task-input font-mono" type="number" value={retries} onChange={(event) => setRetries(event.target.value)} />
            </Field>
          </div>
          <Field label="命令执行沙箱">
            <select className="task-input" value={sandboxMode} onChange={(event) => setSandboxMode(event.target.value as 'docker' | 'host')}>
              <option value="docker">Docker 容器（推荐）</option>
              <option value="host">宿主机兼容模式</option>
            </select>
          </Field>
          {sandboxMode === 'docker' ? (
            <div className={dockerReady ? 'sandbox-note ready' : 'sandbox-note unavailable'}>
              <Container className="size-4 shrink-0" />
              <p>{dockerReady
                ? `无网络 · 1 CPU · 512 MB · 128 进程 · 最大增长 256 MB · ${runtime?.docker.image}`
                : `Docker 暂不可用：${runtime?.docker.reason ?? '请启动 Docker Desktop 并准备基础镜像'}`}</p>
            </div>
          ) : (
            <div className="sandbox-note warning">
              <CircleAlert className="size-4 shrink-0" />
              <p>兼容模式会在隔离 worktree 内直接运行命令，但不提供容器级网络和资源隔离。</p>
            </div>
          )}
          <label className="consent-row text-xs">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            <span>我已逐项审阅并批准此验收契约。</span>
          </label>
          <Button
            className="w-full bg-cyan-300 text-slate-950 hover:bg-cyan-200"
            disabled={!confirmed || !model.trim() || !providerConfigured || !sandboxReady || submitting}
            onClick={() => void approve()}
          >
            {submitting ? <LoaderCircle className="animate-spin" /> : <Play />}
            批准并启动 Agent
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function ContractContents({ plan }: { plan: AcceptancePlan }) {
  return (
    <>
      <p className="text-sm leading-relaxed text-foreground/85">{plan.summary}</p>
      <ContractList title="验收条件" items={plan.acceptance_criteria} />
      <div className="grid gap-5 lg:grid-cols-2">
        <ContractList title="必须保持" items={plan.preserved_behaviors} />
        <ContractList title="边界情况" items={plan.edge_cases} />
      </div>
      <section>
        <h3 className="contract-title">结构化外部用例 · {plan.python_cases.length}</h3>
        <div className="space-y-3">
          {plan.python_cases.map((item) => (
            <div key={item.name} className="acceptance-case">
              <div className="flex flex-wrap items-center gap-2">
                <strong>{item.name}</strong>
                <code>{item.module}.{item.callable}</code>
              </div>
              <p>参数：<code>{item.args_json}</code> · 预期：<code>{item.expectation === 'equals' ? item.expected_json : item.exception_type}</code></p>
              <p>{item.rationale}</p>
            </div>
          ))}
        </div>
      </section>
      <div className="grid gap-5 lg:grid-cols-2">
        <ContractList title="允许修改" items={plan.allowed_paths} code />
        <ContractList
          title="验证命令"
          items={plan.validation_commands.map((command) => JSON.stringify(command))}
          code
        />
      </div>
      <ContractList title="规划证据" items={plan.evidence_files} code />
      <div className="rounded-lg border border-white/8 bg-black/20 p-3">
        <p className="text-xs text-muted-foreground">契约 SHA-256</p>
        <code className="mt-1 block break-all text-xs text-cyan-100">{plan.contract_sha256}</code>
      </div>
    </>
  );
}

function ContractEditor({
  job,
  plan,
  onSaved,
  onCancel,
  onError,
}: {
  job: Job;
  plan: AcceptancePlan;
  onSaved: (job: Job) => void;
  onCancel: () => void;
  onError: (reason: unknown) => void;
}) {
  const [summary, setSummary] = useState(plan.summary);
  const [criteria, setCriteria] = useState(plan.acceptance_criteria.join('\n'));
  const [preserved, setPreserved] = useState(plan.preserved_behaviors.join('\n'));
  const [edges, setEdges] = useState(plan.edge_cases.join('\n'));
  const [allowedPaths, setAllowedPaths] = useState(plan.allowed_paths.join('\n'));
  const [commands, setCommands] = useState(
    plan.validation_commands.map((command) => JSON.stringify(command)).join('\n'),
  );
  const [note, setNote] = useState('人工修订验收契约');
  const [submitting, setSubmitting] = useState(false);

  const save = async () => {
    setSubmitting(true);
    try {
      const updated = await api<Job>(`/api/jobs/${job.job_id}/contract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contract_sha256: plan.contract_sha256,
          acceptance_criteria: lines(criteria),
          preserved_behaviors: lines(preserved),
          edge_cases: lines(edges),
          allowed_paths: lines(allowedPaths),
          validation_commands: parseCommands(commands),
          python_cases: plan.python_cases,
          summary: summary.trim(),
          revision_note: note.trim(),
        }),
      });
      onSaved(updated);
    } catch (reason) {
      onError(reason);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="contract-editor space-y-5">
      <div className="rounded-lg border border-amber-300/20 bg-amber-300/[0.05] p-4 text-sm text-amber-100">
        保存会生成新的契约哈希并使旧审批失效。结构化外部用例保持只读，避免人工文本与可执行验收意外脱节。
      </div>
      <Field label="契约摘要">
        <textarea className="task-input min-h-24 resize-y" value={summary} onChange={(event) => setSummary(event.target.value)} />
      </Field>
      <div className="grid gap-5 lg:grid-cols-2">
        <Field label="验收条件" hint="每行一项，至少保留一项。">
          <textarea className="task-input min-h-40 resize-y" value={criteria} onChange={(event) => setCriteria(event.target.value)} />
        </Field>
        <Field label="允许修改的路径" hint="每行一个 glob，至少保留一项。">
          <textarea className="task-input min-h-40 resize-y font-mono" value={allowedPaths} onChange={(event) => setAllowedPaths(event.target.value)} />
        </Field>
        <Field label="必须保持的行为" hint="每行一项，可留空。">
          <textarea className="task-input min-h-32 resize-y" value={preserved} onChange={(event) => setPreserved(event.target.value)} />
        </Field>
        <Field label="边界情况" hint="每行一项，可留空。">
          <textarea className="task-input min-h-32 resize-y" value={edges} onChange={(event) => setEdges(event.target.value)} />
        </Field>
      </div>
      <Field label="验证命令" hint="每行一个 JSON 参数数组，至少保留一条。">
        <textarea className="task-input min-h-28 resize-y font-mono" value={commands} onChange={(event) => setCommands(event.target.value)} />
      </Field>
      <Field label="本次修改说明">
        <input className="task-input" value={note} onChange={(event) => setNote(event.target.value)} />
      </Field>
      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onCancel} disabled={submitting}>
          <X data-icon="inline-start" />取消编辑
        </Button>
        <Button
          className="bg-cyan-300 text-slate-950 hover:bg-cyan-200"
          onClick={() => void save()}
          disabled={submitting || !summary.trim() || !lines(criteria).length || !lines(allowedPaths).length || !lines(commands).length || !note.trim()}
        >
          {submitting ? <LoaderCircle className="animate-spin" /> : <PencilLine />}
          保存为新版本
        </Button>
      </div>
    </div>
  );
}

function NeedsInput({
  job,
  plan,
  runtime,
  onUpdated,
  onError,
}: {
  job: Job;
  plan: AcceptancePlan;
  runtime: RuntimeInfo | null;
  onUpdated: (job: Job) => void;
  onError: (reason: unknown) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>(
    Object.fromEntries(plan.questions.map((question) => [question, ''])),
  );
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const providerConfigured = runtime?.providers[job.planning_request.provider] ?? false;

  const clarify = async () => {
    setSubmitting(true);
    try {
      const updated = await api<Job>(`/api/jobs/${job.job_id}/clarify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contract_sha256: plan.contract_sha256,
          answers: plan.questions.map((question) => ({ question, answer: answers[question]?.trim() })),
        }),
      });
      onUpdated(updated);
    } catch (reason) {
      onError(reason);
    } finally {
      setSubmitting(false);
    }
  };

  if (editing) {
    return (
      <Card className="border-cyan-300/18 bg-card/75">
        <CardHeader><CardTitle className="flex items-center gap-2"><PencilLine className="size-4 text-cyan-300" />直接编辑契约</CardTitle></CardHeader>
        <CardContent className="space-y-6">
          <ContractEditor job={job} plan={plan} onSaved={onUpdated} onCancel={() => setEditing(false)} onError={onError} />
          <RevisionHistory revisions={job.contract_revisions} currentSha={plan.contract_sha256} />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="border-amber-300/20 bg-amber-300/[0.04]">
        <CardHeader><CardTitle className="flex items-center gap-2"><MessageSquareText className="size-4 text-amber-200" />回答规划问题</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <p className="text-sm leading-relaxed text-muted-foreground">
            回答会保存在当前任务中，独立规划器只修订受影响的契约内容；无需重新创建任务。
          </p>
          {plan.questions.map((question, index) => (
            <Field key={question} label={`${index + 1}. ${question}`}>
              <textarea
                className="task-input min-h-28 resize-y"
                value={answers[question] ?? ''}
                onChange={(event) => setAnswers({ ...answers, [question]: event.target.value })}
                placeholder="输入明确、可验收的答案"
              />
            </Field>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/8 pt-5">
            <Button variant="outline" onClick={() => setEditing(true)}>
              <PencilLine data-icon="inline-start" />直接编辑现有契约
            </Button>
            <Button
              className="bg-cyan-300 text-slate-950 hover:bg-cyan-200"
              onClick={() => void clarify()}
              disabled={submitting || !providerConfigured || plan.questions.some((question) => !answers[question]?.trim())}
            >
              {submitting ? <LoaderCircle className="animate-spin" /> : <Send />}
              提交回答并修订
            </Button>
          </div>
          {!providerConfigured && <p className="text-xs text-amber-200">规划 Provider 的服务端 Key 未配置，暂时只能直接编辑契约。</p>}
        </CardContent>
      </Card>
      <RevisionHistory revisions={job.contract_revisions} currentSha={plan.contract_sha256} />
    </div>
  );
}

function RevisionHistory({ revisions, currentSha }: { revisions: ContractRevision[]; currentSha: string }) {
  return (
    <Card className="revision-card border-white/8 bg-black/15">
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><History className="size-4 text-cyan-300" />契约修订记录</CardTitle></CardHeader>
      <CardContent>
        <div className="space-y-3">
          {[...revisions].reverse().map((revision) => (
            <div key={revision.revision} className="revision-row" data-current={revision.contract_sha256 === currentSha}>
              <div className="flex flex-wrap items-center gap-2">
                <strong>v{revision.revision}</strong>
                <Badge variant="outline">{revisionSourceLabel(revision.source)}</Badge>
                {revision.contract_sha256 === currentSha && <Badge className="bg-cyan-300 text-slate-950">当前</Badge>}
              </div>
              <p>{revision.note}</p>
              <div className="flex flex-wrap justify-between gap-2 font-mono text-xs text-muted-foreground">
                <span>{revision.contract_sha256.slice(0, 12)}</span>
                <time>{formatDateTime(revision.created_at)}</time>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function LiveProgress({ job }: { job: Job }) {
  const tokens = job.plan?.token_usage.total_tokens;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="border-white/8 bg-card/75">
        <CardHeader><CardTitle className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin text-cyan-300" />{job.status === 'CANCEL_REQUESTED' ? '正在安全停止' : '任务进行中'}</CardTitle></CardHeader>
        <CardContent>
          <div className="phase-track">
            {['PLANNING', 'REPLANNING', 'AWAITING_APPROVAL', 'RUNNING', 'SUCCEEDED'].map((phase) => (
              <div key={phase} data-active={job.phase === phase || job.status === phase}><span />{phaseLabel(phase)}</div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">最新状态：{job.events.at(-1)?.message ?? '等待后台任务启动'}</p>
          {tokens !== undefined && <p className="mt-2 font-mono text-xs text-cyan-100">规划 Token：{tokens.toLocaleString('zh-CN')}</p>}
        </CardContent>
      </Card>
      <Timeline events={job.events} />
    </div>
  );
}

function RunEvidence({
  job,
  run,
  onUpdated,
  onError,
}: {
  job: Job;
  run: RunResult;
  onUpdated: (job: Job) => void;
  onError: (reason: unknown) => void;
}) {
  return (
    <div className="space-y-5">
      <Tabs defaultValue="verification">
        <TabsList variant="line" className="w-full justify-start border-b border-white/8">
          <TabsTrigger value="verification">验收结果</TabsTrigger>
          <TabsTrigger value="timeline">实时轨迹 · {job.events.length}</TabsTrigger>
          <TabsTrigger value="diff">Git Diff</TabsTrigger>
        </TabsList>
        <TabsContent value="verification" className="pt-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="border-white/8 bg-card/75">
              <CardHeader><CardTitle className="flex items-center gap-2"><ListChecks className="size-4 text-cyan-300" />Verifier 检查</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {run.verification.checks.map((check) => (
                  <div key={check.name} className="check-row">
                    <span className={check.passed ? 'check-icon pass' : 'check-icon fail'}>
                      {check.passed ? <Check /> : <CircleAlert />}
                    </span>
                    <div><p className="text-sm">{checkLabel(check.name)}</p><p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{check.summary}</p></div>
                  </div>
                ))}
              </CardContent>
            </Card>
            <div className="space-y-4">
              <Metric label="模型轮次" value={run.state.round} />
              <Metric label="总 Token" value={run.state.token_usage.total_tokens ?? 0} />
              <Metric label="验收次数" value={run.state.verification_attempts} />
              <Metric label="修改文件" value={run.state.modified_files.length} />
              <Card className="metric-card">
                <CardContent>
                  <p className="text-xs text-muted-foreground">执行边界</p>
                  <p className="mt-2 flex items-center gap-2 text-sm"><Container className="size-4 text-cyan-300" />{run.task?.sandbox?.mode === 'docker' ? 'Docker 无网络沙箱' : '宿主机兼容模式'}</p>
                  {run.task?.sandbox?.mode === 'docker' && <p className="mt-2 font-mono text-xs text-muted-foreground">{run.task.sandbox.cpus} CPU · {run.task.sandbox.memory_mb} MB · {run.task.sandbox.pids_limit} PIDs · +{run.task.sandbox.workspace_growth_mb} MB</p>}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="timeline" className="pt-4"><Timeline events={job.events} /></TabsContent>
        <TabsContent value="diff" className="pt-4">
          {run.git_diff ? <pre className="diff-block mt-0"><code>{run.git_diff}</code></pre> : (
            <Empty className="border border-dashed border-white/10"><EmptyHeader><EmptyMedia variant="icon"><FileDiff /></EmptyMedia><EmptyTitle>没有代码差异</EmptyTitle><EmptyDescription>任务未产生可应用的补丁。</EmptyDescription></EmptyHeader></Empty>
          )}
        </TabsContent>
      </Tabs>
      {run.verification.passed && job.plan && job.patch_sha256 && (
        <DeliveryPanel key={job.deliveries.length} job={job} onUpdated={onUpdated} onError={onError} />
      )}
    </div>
  );
}

function DeliveryPanel({
  job,
  onUpdated,
  onError,
}: {
  job: Job;
  onUpdated: (job: Job) => void;
  onError: (reason: unknown) => void;
}) {
  const delivery = job.deliveries.at(-1);
  const retrySuffix = delivery && delivery.status !== 'SUCCEEDED' ? `-retry-${delivery.attempt + 1}` : '';
  const defaultBranch = delivery
    ? `${delivery.request.branch_name}${retrySuffix}`
    : `amor/task-${job.job_id.slice(-8)}`;
  const [branchName, setBranchName] = useState(defaultBranch);
  const [commitRequested, setCommitRequested] = useState(true);
  const [commitMessage, setCommitMessage] = useState('fix: apply verified AMOR patch');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const deliver = async () => {
    if (!job.plan || !job.patch_sha256) return;
    setSubmitting(true);
    try {
      const updated = await api<Job>(`/api/jobs/${job.job_id}/deliver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contract_sha256: job.plan.contract_sha256,
          patch_sha256: job.patch_sha256,
          branch_name: branchName.trim(),
          commit_requested: commitRequested,
          commit_message: commitMessage.trim(),
          confirm_apply: confirmed,
        }),
      });
      onUpdated(updated);
    } catch (reason) {
      onError(reason);
    } finally {
      setSubmitting(false);
    }
  };

  if (delivery?.status === 'QUEUED' || delivery?.status === 'RUNNING') {
    return (
      <Card className="border-cyan-300/20 bg-cyan-300/[0.035]">
        <CardHeader><CardTitle className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin text-cyan-300" />正在安全交付补丁</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>AMOR 正在独立 worktree 中创建 <code>{delivery.request.branch_name}</code>，应用同一补丁并重新执行 Verifier。</p>
          <p className="font-mono text-xs text-cyan-100">patch {delivery.request.patch_sha256}</p>
        </CardContent>
      </Card>
    );
  }

  if (delivery?.status === 'SUCCEEDED' && delivery.report) {
    return (
      <Card className="border-emerald-400/20 bg-emerald-400/[0.035]">
        <CardHeader><CardTitle className="flex items-center gap-2"><PackageCheck className="size-4 text-emerald-300" />补丁已安全交付</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <div className="delivery-result-grid">
            <div><span>本地分支</span><code>{delivery.report.branch_name}</code></div>
            <div><span>本地 Commit</span><code>{delivery.report.commit_sha ?? '未提交，保留在交付 worktree'}</code></div>
            <div><span>交付工作区</span><code>{delivery.workspace_artifact ?? '—'}</code></div>
            <div><span>补丁指纹</span><code>{delivery.report.patch_sha256}</code></div>
          </div>
          <div>
            <h3 className="contract-title">落地后二次验收</h3>
            <div className="space-y-3">
              {delivery.report.verification?.checks.map((check) => (
                <div key={check.name} className="check-row">
                  <span className={check.passed ? 'check-icon pass' : 'check-icon fail'}>{check.passed ? <Check /> : <CircleAlert />}</span>
                  <div><p className="text-sm">{checkLabel(check.name)}</p><p className="mt-1 text-xs text-muted-foreground">{check.summary}</p></div>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">原仓库当前分支和工作副本没有被切换或修改；如需远端协作，可在终端对这份交付报告显式执行 <code>amor publish-pr</code>，系统只会创建新的 Draft PR。</p>
        </CardContent>
      </Card>
    );
  }

  const canStart = job.status === 'SUCCEEDED' || job.status === 'DELIVERY_FAILED';
  return (
    <Card className="border-white/8 bg-card/75">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><GitBranch className="size-4 text-cyan-300" />交付已验收补丁</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {delivery?.status === 'FAILED' && (
          <div className="rounded-lg border border-rose-400/25 bg-rose-400/[0.06] p-4 text-sm text-rose-100">
            上一次交付失败：{delivery.error ?? delivery.report?.error ?? '未通过落地后验收'}。失败现场已保留，请使用新的分支名重试。
          </div>
        )}
        {delivery?.status === 'CANCELLED' && (
          <div className="rounded-lg border border-amber-300/20 bg-amber-300/[0.05] p-4 text-sm text-amber-100">上一次交付已取消，原始验收结果仍然有效。</div>
        )}
        <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
          <Field label="新建本地分支" hint="分支必须不存在；原仓库当前分支不会被切换。">
            <input className="task-input font-mono" value={branchName} onChange={(event) => setBranchName(event.target.value)} />
          </Field>
          <Field label="已验收补丁 SHA-256">
            <input className="task-input font-mono" value={job.patch_sha256 ?? ''} readOnly />
          </Field>
        </div>
        <label className="consent-row">
          <input type="checkbox" checked={commitRequested} onChange={(event) => setCommitRequested(event.target.checked)} />
          <span><strong className="text-foreground">生成本地 Commit</strong><br />关闭后，补丁会保留在独立交付 worktree 中等待人工检查。</span>
        </label>
        {commitRequested && (
          <Field label="Commit 信息">
            <div className="relative">
              <GitCommitHorizontal className="pointer-events-none absolute top-3 left-3 size-4 text-muted-foreground" />
              <input className="task-input pl-10" value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} />
            </div>
          </Field>
        )}
        <label className="consent-row">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          <span>我确认将当前 SHA-256 对应的已验收补丁应用到新的本地分支，并重新运行相同验收。</span>
        </label>
        <div className="flex justify-end">
          <Button
            className="bg-cyan-300 text-slate-950 hover:bg-cyan-200"
            onClick={() => void deliver()}
            disabled={!canStart || submitting || !confirmed || !branchName.trim() || (commitRequested && !commitMessage.trim())}
          >
            {submitting ? <LoaderCircle className="animate-spin" /> : <PackageCheck />}
            创建分支并重新验收
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Timeline({ events }: { events: JobEvent[] }) {
  return (
    <Card className="border-white/8 bg-card/75">
      <CardHeader><CardTitle className="flex items-center gap-2"><TerminalSquare className="size-4 text-cyan-300" />事件轨迹</CardTitle></CardHeader>
      <CardContent>
        <ScrollArea className="max-h-[36rem]">
          <div className="trace-line pr-3">
            {events.map((event) => (
              <div key={event.sequence} className="trace-event">
                <span className="trace-dot" />
                <div>
                  <div className="flex flex-wrap items-center gap-2"><code>{event.kind}</code><Badge variant="outline">{event.phase}</Badge></div>
                  <p>{event.message}</p>
                  <time>{formatDateTime(event.created_at)}</time>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function ContractList({ title, items, code = false }: { title: string; items: string[]; code?: boolean }) {
  return (
    <section>
      <h3 className="contract-title">{title}</h3>
      {items.length ? <ul className="space-y-2">{items.map((item) => <li key={item} className="contract-item">{code ? <code>{item}</code> : item}</li>)}</ul> : <p className="text-sm text-muted-foreground">无</p>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <Card className="metric-card"><CardContent><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 font-mono text-2xl">{value.toLocaleString('zh-CN')}</p></CardContent></Card>;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="grid gap-2 text-sm"><span className="font-medium">{label}</span>{children}{hint && <span className="text-xs leading-relaxed text-muted-foreground">{hint}</span>}</label>;
}

function JobStatusBadge({ status }: { status: string }) {
  const successful = status === 'SUCCEEDED';
  const warning = ['AWAITING_APPROVAL', 'NEEDS_INPUT', 'BLOCKED', 'DELIVERY_FAILED', 'CANCEL_REQUESTED'].includes(status);
  const active = activeStatuses.has(status) && status !== 'CANCEL_REQUESTED';
  return (
    <Badge variant="outline" className={successful ? 'border-emerald-400/35 bg-emerald-400/10 text-emerald-300' : warning ? 'border-amber-300/35 bg-amber-300/10 text-amber-200' : active ? 'border-cyan-300/35 bg-cyan-300/10 text-cyan-200' : 'border-rose-400/35 bg-rose-400/10 text-rose-300'}>
      {active && <LoaderCircle className="size-3 animate-spin" />}{jobStatusLabel(status)}
    </Badge>
  );
}

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function parseCommands(value: string): string[][] {
  return lines(value).map((line, index) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      throw new Error(`第 ${index + 1} 条验证命令不是有效 JSON`);
    }
    if (!Array.isArray(parsed) || !parsed.length || !parsed.every((item) => typeof item === 'string' && item)) {
      throw new Error(`第 ${index + 1} 条验证命令必须是非空字符串数组`);
    }
    return parsed as string[];
  });
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string'
      ? payload.detail
      : Array.isArray(payload?.detail)
        ? payload.detail
            .map((item) => {
              if (typeof item !== 'object' || item === null) return String(item);
              const record = item as { loc?: unknown[]; msg?: unknown };
              const message = typeof record.msg === 'string' ? record.msg : '无效';
              return `${record.loc?.slice(1).join('.') ?? '参数'}：${message}`;
            })
            .join('；')
        : `API 返回 ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : '发生未知错误';
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
}

function jobStatusLabel(status: string): string {
  return {
    QUEUED: '等待规划', PLANNING: '规划中', REPLANNING: '修订中', AWAITING_APPROVAL: '等待审批', NEEDS_INPUT: '需要信息',
    EXECUTION_QUEUED: '等待执行', RUNNING: '执行中', SUCCEEDED: '验收通过', FAILED: '执行失败',
    DELIVERY_QUEUED: '等待交付', DELIVERING: '交付验收中', DELIVERY_FAILED: '交付失败',
    BLOCKED: '安全阻断', BUDGET_EXHAUSTED: '预算耗尽', CANCEL_REQUESTED: '正在取消', CANCELLED: '已取消',
  }[status] ?? status;
}

function phaseLabel(phase: string): string {
  return { PLANNING: '验收规划', REPLANNING: '契约修订', AWAITING_APPROVAL: '人工审批', RUNNING: 'Agent 执行', DELIVERY_QUEUED: '等待交付', DELIVERING: '交付验收', DELIVERED: '已交付', DELIVERY_FAILED: '交付失败', SUCCEEDED: '最终验收' }[phase] ?? phase;
}

function revisionSourceLabel(source: ContractRevision['source']): string {
  return { planner: '初始规划', clarification: '问题回答', manual: '人工编辑' }[source];
}

function checkLabel(name: string): string {
  if (name.startsWith('visible_tests_')) return `可见测试 ${name.slice('visible_tests_'.length)}`;
  return { agent_loop: 'Agent 执行流程', scope: '修改范围', static_compile: '静态编译', external_acceptance: '外部验收契约', hidden_tests: '隐藏验收测试' }[name] ?? name;
}

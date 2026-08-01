import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

type Server = {
  id: string
  name: string
  adapter: string
  status: string
  online_players: number
  max_players: number
  capabilities: string[]
}

type Run = {
  id: string
  status: string
  answer?: {
    summary: string
    recommendations: string[]
    executed_tools: string[]
  }
}

type Approval = {
  id: string
  run_id: string
  tool_name: string
  server_id: string
  status: string
  arguments: Record<string, unknown>
}

type Provider = { id: string; name: string; protocol: string; base_url: string; model: string; api_key_env: string; enabled: boolean }
type ProviderProbe = { provider_id: string; api_key_configured: boolean; live: boolean; reachable?: boolean; model_available?: boolean; capabilities: Record<string, string>; error?: string }
type Policy = { tool_name: string; risk: string; mode: string; timeout_seconds: number }
type Audit = { id: string; action: string; tool_name?: string; status: string; created_at: string }
type ServerConfig = { id: string; name: string; adapter: string; enabled: boolean; root?: string; command: string[]; log_path: string; world_path: string; rcon_host?: string; rcon_port: number; rcon_password_env?: string }
type Backup = { id: string; server_id: string; created_at: string; size_bytes: number; sha256: string; verified: boolean; path?: string }
type ModProject = { id: string; name: string; root: string; kind: string; minecraft_version?: string; description?: string; build_command: string[]; enabled: boolean }
type ModFile = { path: string; size_bytes: number; sha256: string; language: string }
type ModInspection = { summary: string; project: ModProject; files: ModFile[]; detected_features: string[]; warnings: string[]; next_actions: string[] }
type ModScenario = { id: string; project_id: string; kind: string; title: string; steps: string[]; assertions: string[]; status: string; evidence_ids: string[] }
type ModPatch = { id: string; project_id: string; title: string; rationale: string; status: string; changes: { path: string; operation: string }[]; error?: string }
type ModEvidence = { id: string; kind: string; title: string; excerpt: string; created_at: string }
type ModPlan = { id: string; objective: string; steps: string[]; scenario_kind?: string; next_actions: string[] }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail ?? body.error?.message ?? '请求失败')
  return body.data as T
}

function App() {
  const [prompt, setPrompt] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [modProjectId, setModProjectId] = useState('demo-mod')
  const [modKind, setModKind] = useState('new_item')
  const [modMessage, setModMessage] = useState('')
  const [modProjectForm, setModProjectForm] = useState({ id: 'my-mod', name: '我的模组', root: '', kind: 'fabric' })
  const [providerId, setProviderId] = useState('')
  const [providerForm, setProviderForm] = useState({ id: 'anlapi', name: 'anlapi 推荐线路', protocol: 'openai-compatible-chat', base_url: 'https://api.anlmc.top/v1', model: '', api_key_env: 'OPENAI_API_KEY' })
  const [serverConfigForm, setServerConfigForm] = useState({ id: 'bds-main', name: '我的 BDS', adapter: 'bds-process', root: '', command: 'bedrock_server.exe', log_path: 'logs/latest.log', world_path: 'worlds', rcon_host: '127.0.0.1', rcon_port: '19132', rcon_password_env: 'ENDSTONE_RCON_PASSWORD' })

  const servers = useQuery({
    queryKey: ['servers'],
    queryFn: () => api<Server[]>('/api/v1/servers'),
    refetchInterval: 5000,
  })
  const approvals = useQuery({
    queryKey: ['approvals'],
    queryFn: () => api<Approval[]>('/api/v1/approvals?pending_only=true'),
    refetchInterval: 2000,
  })
  const providers = useQuery({ queryKey: ['providers'], queryFn: () => api<Provider[]>('/api/v1/providers') })
  const serverConfigs = useQuery({ queryKey: ['server-configs'], queryFn: () => api<ServerConfig[]>('/api/v1/servers/configs') })
  const policies = useQuery({ queryKey: ['policies'], queryFn: () => api<Policy[]>('/api/v1/tool-policies') })
  const audits = useQuery({ queryKey: ['audits'], queryFn: () => api<Audit[]>('/api/v1/audit-events') })
  const modProjects = useQuery({ queryKey: ['mod-projects'], queryFn: () => api<ModProject[]>('/api/v1/mod-projects') })
  const modInspection = useQuery({ queryKey: ['mod-inspection', modProjectId], queryFn: () => api<ModInspection>(`/api/v1/mod-projects/${modProjectId}`), enabled: Boolean(modProjectId) })
  const modPlans = useQuery({ queryKey: ['mod-plans', modProjectId], queryFn: () => api<ModPlan[]>(`/api/v1/mod-projects/${modProjectId}/plans`), enabled: Boolean(modProjectId) })
  const modScenarios = useQuery({ queryKey: ['mod-scenarios', modProjectId], queryFn: () => api<ModScenario[]>(`/api/v1/mod-projects/${modProjectId}/scenarios`), enabled: Boolean(modProjectId) })
  const modPatches = useQuery({ queryKey: ['mod-patches', modProjectId], queryFn: () => api<ModPatch[]>(`/api/v1/mod-projects/${modProjectId}/patches`), enabled: Boolean(modProjectId) })
  const modEvidence = useQuery({ queryKey: ['mod-evidence', modProjectId], queryFn: () => api<ModEvidence[]>(`/api/v1/mod-projects/${modProjectId}/evidence`), enabled: Boolean(modProjectId) })

  const demoServer = servers.data?.[0]
  const backups = useQuery({ queryKey: ['backups', demoServer?.id], queryFn: () => api<Backup[]>(`/api/v1/servers/${demoServer?.id}/backups`), enabled: Boolean(demoServer?.id), refetchInterval: 5000 })
  const healthLabel = useMemo(() => {
    if (!demoServer) return '连接中'
    return demoServer.status === 'online' ? '运行正常' : '已停止'
  }, [demoServer])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!prompt.trim()) return
    setBusy(true)
    setMessage('')
    setEvents([])
    try {
      const created = await api<Run>('/api/v1/runs', {
        method: 'POST',
        body: JSON.stringify({ prompt, server_id: demoServer?.id ?? 'demo', provider_id: providerId || null }),
      })
      setRun(created)
      const source = new EventSource(`/api/v1/runs/${created.id}/events`)
      const handleEvent = (incoming: MessageEvent<string>) => {
        const data = JSON.parse(incoming.data) as { message: string }
        setEvents((current) => [...current, data.message])
        if (data.message.includes('完成') || data.message.includes('审批')) source.close()
      }
      for (const eventName of ['run_started', 'provider_mode', 'agent_step', 'tool_requested', 'tool_completed', 'tool_failed', 'approval_required', 'run_completed', 'run_failed', 'provider_unavailable', 'provider_failed']) {
        source.addEventListener(eventName, handleEvent)
      }
      source.onerror = () => source.close()
      const timer = window.setInterval(async () => {
        const latest = await api<Run>(`/api/v1/runs/${created.id}`)
        setRun(latest)
        if (latest.status !== 'running') window.clearInterval(timer)
      }, 300)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '请求失败')
    } finally {
      setBusy(false)
    }
  }

  async function resolveApproval(approval: Approval, approved: boolean) {
    await api(`/api/v1/approvals/${approval.id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    })
    await Promise.all([approvals.refetch(), modPatches.refetch(), modInspection.refetch(), modEvidence.refetch()])
    if (run?.id === approval.run_id) setRun(await api<Run>(`/api/v1/runs/${run.id}`))
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault()
    if (!providerForm.model.trim()) return
    const existing = providers.data?.find((provider) => provider.id === providerForm.id)
    await api(`/api/v1/providers${existing ? `/${providerForm.id}` : ''}`, {
      method: existing ? 'PATCH' : 'POST',
      body: JSON.stringify(providerForm),
    })
    await providers.refetch()
    setMessage('provider 配置已保存；API Key 仍由环境变量提供。')
  }

  async function probeProvider(live: boolean) {
    if (!providerForm.id) return
    try {
      const result = await api<ProviderProbe>(`/api/v1/providers/${providerForm.id}/probe?live=${live}`)
      const capabilityText = Object.entries(result.capabilities).map(([key, value]) => `${key}:${value}`).join('、')
      setMessage(`${live ? '在线' : '本地'}探测：密钥${result.api_key_configured ? '已配置' : '未配置'}${result.error ? ` · ${result.error}` : ''}${capabilityText ? ` · ${capabilityText}` : ''}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Provider 探测失败')
    }
  }

  async function changePolicy(policy: Policy, mode: string) {
    await api(`/api/v1/tool-policies/${policy.tool_name}`, { method: 'PATCH', body: JSON.stringify({ mode }) })
    await policies.refetch()
  }

  async function createModScenario() {
    try {
      await api<ModScenario>(`/api/v1/mod-projects/${modProjectId}/scenarios`, {
        method: 'POST',
        body: JSON.stringify({ project_id: modProjectId, kind: modKind }),
      })
      await modScenarios.refetch()
      setModMessage('测试场景草稿已创建；它只描述步骤，不会启动真实客户端。')
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '测试场景创建失败')
    }
  }

  async function createModPlan() {
    try {
      await api<ModPlan>(`/api/v1/mod-projects/${modProjectId}/plans`, {
        method: 'POST',
        body: JSON.stringify({ project_id: modProjectId, request: '梳理当前模组需求并规划安全实现和测试步骤' }),
      })
      await modPlans.refetch()
      setModMessage('结构化开发计划已生成；后续写入和构建仍需逐步审批。')
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '计划生成失败')
    }
  }

  async function createModProject(event: FormEvent) {
    event.preventDefault()
    try {
      await api<ModProject>('/api/v1/mod-projects', {
        method: 'POST',
        body: JSON.stringify(modProjectForm),
      })
      await modProjects.refetch()
      setModProjectId(modProjectForm.id)
      setModMessage('模组项目已注册；项目目录必须由你显式提供。')
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '模组项目注册失败')
    }
  }

  async function runModScenario(scenario: ModScenario) {
    try {
      const result = await api<{ status: string; outcome?: { data?: { summary?: string } }; approval_id?: string }>(
        `/api/v1/mod-projects/${modProjectId}/scenarios/${scenario.id}/run`,
        { method: 'POST' },
      )
      setModMessage(result.status === 'pending_approval' ? `需要审批：${result.approval_id}` : result.outcome?.data?.summary || 'Demo 测试已完成')
      await Promise.all([modScenarios.refetch(), modEvidence.refetch()])
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '测试执行失败')
    }
  }

  async function buildModProject() {
    try {
      const result = await api<{ status: string; approval_id?: string }>(`/api/v1/mod-projects/${modProjectId}/builds`, {
        method: 'POST',
        body: JSON.stringify({ project_id: modProjectId, clean: false }),
      })
      setModMessage(result.status === 'pending_approval' ? `构建等待审批：${result.approval_id}` : '构建请求已处理；请查看构建记录和审批队列。')
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '构建请求失败')
    }
  }

  async function applyModPatch(patch: ModPatch) {
    try {
      const result = await api<{ status: string; approval_id?: string }>(`/api/v1/mod-projects/${modProjectId}/patches/${patch.id}/apply`, { method: 'POST' })
      setModMessage(result.status === 'pending_approval' ? `补丁等待审批：${result.approval_id}` : '补丁已应用。')
      await Promise.all([modPatches.refetch(), modInspection.refetch(), modEvidence.refetch()])
    } catch (error) {
      setModMessage(error instanceof Error ? error.message : '补丁应用失败')
    }
  }

  async function saveServerConfig(event: FormEvent) {
    event.preventDefault()
    const command = serverConfigForm.command.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
    const payload: Record<string, unknown> = {
      id: serverConfigForm.id,
      name: serverConfigForm.name,
      adapter: serverConfigForm.adapter,
      root: serverConfigForm.root,
      command,
      log_path: serverConfigForm.log_path,
      world_path: serverConfigForm.world_path,
    }
    if (serverConfigForm.adapter === 'endstone-rcon') {
      payload.rcon_host = serverConfigForm.rcon_host
      payload.rcon_port = Number(serverConfigForm.rcon_port)
      payload.rcon_password_env = serverConfigForm.rcon_password_env
    }
    try {
      await api('/api/v1/servers/configs', { method: 'POST', body: JSON.stringify(payload) })
      await Promise.all([serverConfigs.refetch(), servers.refetch()])
      setMessage('服务器配置已保存并注册；密码仍由环境变量提供。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '服务器配置保存失败')
    }
  }

  useEffect(() => {
    document.title = `ANL MineOps · ${healthLabel}`
  }, [healthLabel])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">A</span><span>ANL MineOps</span></div>
        <p className="eyebrow">SERVER OPERATIONS</p>
        <nav>
          <a className="active" href="#dashboard">总览</a>
          <a href="#assistant">Agent 助手</a>
          <a href="#mod-workbench">模组工作台</a>
          <a href="#approvals">审批队列{approvals.data?.length ? ` · ${approvals.data.length}` : ''}</a>
          <a href="#settings">模型与权限</a>
        </nav>
        <div className="sidebar-footer">本地自托管 · Beta<br />不上传服务器日志</div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div><p className="eyebrow">OPERATIONS CONSOLE</p><h1>服务器总览</h1></div>
          <div className="status-pill"><span className="pulse" /> {healthLabel}</div>
        </header>

        <section id="dashboard" className="metrics-grid">
          <article className="metric-card accent"><span>当前状态</span><strong>{demoServer?.status ?? '—'}</strong><small>DemoAdapter · Endstone</small></article>
          <article className="metric-card"><span>在线玩家</span><strong>{demoServer ? `${demoServer.online_players}/${demoServer.max_players}` : '—'}</strong><small>实时查询</small></article>
          <article className="metric-card"><span>可用工具</span><strong>{demoServer?.capabilities.length ?? 0}</strong><small>策略受控</small></article>
          <article className="metric-card"><span>待审批</span><strong>{approvals.data?.length ?? 0}</strong><small>需要人工确认</small></article>
        </section>

        <section id="assistant" className="workspace-grid">
          <article className="panel chat-panel">
            <div className="panel-heading"><div><p className="eyebrow">NATURAL LANGUAGE OPS</p><h2>问问你的服务器</h2></div><span className="tag">PydanticAI</span></div>
            <div className="answer-area">
              {run?.answer ? <><div className="answer-summary">{run.answer.summary}</div><div className="tool-list">{run.answer.executed_tools.map((tool) => <span key={tool} className="tool-chip">✓ {tool}</span>)}</div></> : <div className="empty-state">输入一个问题，Agent 会先读取证据，再根据工具策略决定是否执行操作。</div>}
              {events.length > 0 && <div className="event-stream">{events.map((item, index) => <div key={`${item}-${index}`}><span>›</span>{item}</div>)}</div>}
            </div>
            <form className="prompt-form" onSubmit={submit}>
              <select className="provider-picker" value={providerId} onChange={(event) => setProviderId(event.target.value)} aria-label="模型 Provider"><option value="">演示模式（不调用模型）</option>{providers.data?.filter((provider) => provider.enabled).map((provider) => <option value={provider.id} key={provider.id}>{provider.name}</option>)}</select>
              <input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：检查最近崩溃日志，或者服务器现在状态怎么样？" />
              <button disabled={busy}>{busy ? '处理中…' : '发送'}</button>
            </form>
            {message && <p className="error-text">{message}</p>}
          </article>

          <article id="approvals" className="panel approval-panel">
            <div className="panel-heading"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h2>审批队列</h2></div><span className="tag warning">可配置</span></div>
            {approvals.data?.length ? approvals.data.map((approval) => <div className="approval-item" key={approval.id}><div><strong>{approval.tool_name}</strong><small>{approval.server_id} · 一次性审批</small></div><div className="approval-actions"><button className="ghost" onClick={() => resolveApproval(approval, false)}>拒绝</button><button onClick={() => resolveApproval(approval, true)}>批准</button></div></div>) : <div className="empty-state compact">当前没有待审批的写操作。</div>}
          </article>
        </section>

        <section id="mod-workbench" className="mod-workbench-grid">
          <article className="panel settings-card">
            <div className="panel-heading">
              <div><p className="eyebrow">EXPERIMENTAL MOD WORKBENCH</p><h2>模组开发与验证</h2></div>
              <span className="tag">安全 MVP</span>
            </div>
            <div className="settings-form">
              <label>模组项目
                <select value={modProjectId} onChange={(event) => setModProjectId(event.target.value)}>
                  {modProjects.data?.map((project) => <option value={project.id} key={project.id}>{project.name} · {project.kind}</option>)}
                </select>
              </label>
              <details className="mod-project-create">
                <summary>注册本地模组项目</summary>
                <form className="settings-form" onSubmit={createModProject}>
                  <label>项目 ID<input value={modProjectForm.id} onChange={(event) => setModProjectForm({ ...modProjectForm, id: event.target.value.toLowerCase() })} /></label>
                  <label>项目名称<input value={modProjectForm.name} onChange={(event) => setModProjectForm({ ...modProjectForm, name: event.target.value })} /></label>
                  <label>项目根目录<input value={modProjectForm.root} onChange={(event) => setModProjectForm({ ...modProjectForm, root: event.target.value })} placeholder="例如：D:\\MinecraftProjects\\my-mod" /></label>
                  <label>Loader<select value={modProjectForm.kind} onChange={(event) => setModProjectForm({ ...modProjectForm, kind: event.target.value })}><option value="fabric">Fabric</option><option value="forge">Forge</option><option value="neoforge">NeoForge</option><option value="bedrock-addon">基岩版 Add-on</option><option value="generic">通用项目</option></select></label>
                  <button>注册项目</button>
                </form>
              </details>
              {modInspection.data && <>
                <div className="mod-summary">{modInspection.data.summary}</div>
                <div className="tool-list">{modInspection.data.detected_features.map((feature) => <span className="tool-chip" key={feature}>✓ {feature}</span>)}</div>
                <div className="mod-file-list">
                  {modInspection.data.files.slice(0, 12).map((file) => <div className="mod-file-row" key={file.path}><span>{file.path}</span><small>{file.language} · {(file.size_bytes / 1024).toFixed(1)} KB</small></div>)}
                </div>
                {modInspection.data.warnings.length > 0 && <p className="settings-note">提示：{modInspection.data.warnings.join('、')}</p>}
              </>}
              <div className="button-row">
                <button type="button" className="ghost" onClick={() => modInspection.refetch()}>重新分析</button>
                <button type="button" className="ghost" onClick={createModPlan}>生成计划</button>
                <button type="button" onClick={buildModProject}>受控构建</button>
              </div>
              {modPlans.data?.[0] && <p className="settings-note">最近计划：{modPlans.data[0].objective} · {modPlans.data[0].steps.length} 步</p>}
            </div>
          </article>

          <article className="panel settings-card">
            <div className="panel-heading">
              <div><p className="eyebrow">PLAN → EXECUTE → EVIDENCE</p><h2>测试场景与证据</h2></div>
              <span className="tag warning">Demo 适配器</span>
            </div>
            <div className="settings-form">
              <label>场景模板
                <select value={modKind} onChange={(event) => setModKind(event.target.value)}>
                  <option value="new_item">新物品</option>
                  <option value="new_block">新方块</option>
                  <option value="new_recipe">新配方</option>
                  <option value="entity_behavior">实体行为</option>
                  <option value="player_interaction">玩家交互</option>
                  <option value="hud_gui">HUD / GUI</option>
                </select>
              </label>
              <button type="button" onClick={createModScenario}>创建测试场景</button>
            </div>
            <div className="mod-list-block">
              {modScenarios.data?.slice(0, 5).map((scenario) => <div className="mod-action-row" key={scenario.id}><span><strong>{scenario.title}</strong><small>{scenario.kind} · {scenario.status}</small></span><button type="button" className="ghost" onClick={() => runModScenario(scenario)}>运行 Demo</button></div>)}
              {!modScenarios.data?.length && <div className="empty-state compact">还没有测试场景。</div>}
            </div>
            <div className="mod-list-block">
              <p className="eyebrow">PATCH QUEUE</p>
              {modPatches.data?.slice(0, 4).map((patch) => <div className="mod-action-row" key={patch.id}><span><strong>{patch.title}</strong><small>{patch.status} · {patch.changes.map((change) => change.path).join('、')}</small></span>{patch.status === 'proposed' && <button type="button" className="ghost" onClick={() => applyModPatch(patch)}>申请应用</button>}</div>)}
              {!modPatches.data?.length && <div className="empty-state compact">Agent 提出的补丁会出现在这里，应用前需要审批。</div>}
            </div>
            <div className="mod-list-block">
              <p className="eyebrow">EVIDENCE</p>
              {modEvidence.data?.slice(0, 4).map((item) => <div className="audit-row" key={item.id}><span>{item.kind} · {item.title}</span><small>{new Date(item.created_at).toLocaleString()}</small></div>)}
            </div>
            {modMessage && <p className="settings-note">{modMessage}</p>}
          </article>
        </section>

        <section id="settings" className="settings-grid">
          <article className="panel settings-card"><div className="panel-heading"><div><p className="eyebrow">MODEL PROVIDER</p><h2>自定义模型接口</h2></div><span className="tag">不保存密钥</span></div>
            <form className="settings-form" onSubmit={saveProvider}><label>Provider ID<input value={providerForm.id} onChange={(event) => setProviderForm({ ...providerForm, id: event.target.value.toLowerCase() })} /></label><label>显示名称<input value={providerForm.name} onChange={(event) => setProviderForm({ ...providerForm, name: event.target.value })} /></label><label>协议<select value={providerForm.protocol} onChange={(event) => setProviderForm({ ...providerForm, protocol: event.target.value })}><option value="openai-compatible-chat">OpenAI-compatible Chat</option><option value="openai-compatible-responses">OpenAI-compatible Responses</option></select></label><label>Base URL<input value={providerForm.base_url} onChange={(event) => setProviderForm({ ...providerForm, base_url: event.target.value })} /></label><label>模型名<input value={providerForm.model} onChange={(event) => setProviderForm({ ...providerForm, model: event.target.value })} placeholder="例如：gpt-5.6" /></label><label>API Key 环境变量<input value={providerForm.api_key_env} onChange={(event) => setProviderForm({ ...providerForm, api_key_env: event.target.value.toUpperCase() })} /></label><div className="button-row"><button>保存 provider</button><button type="button" className="ghost" onClick={() => probeProvider(false)}>检查配置</button><button type="button" className="ghost" onClick={() => probeProvider(true)}>在线探测</button></div></form>
            <p className="settings-note">已配置：{providers.data?.map((provider) => provider.name).join('、') || '尚未配置'} · <a href="https://api.anlmc.top" target="_blank" rel="noreferrer">了解 anlapi ↗</a></p>
          </article>
          <article className="panel settings-card"><div className="panel-heading"><div><p className="eyebrow">SERVER ADAPTER</p><h2>添加服务器</h2></div><span className="tag">显式配置</span></div>
            <form className="settings-form" onSubmit={saveServerConfig}><label>服务器 ID<input value={serverConfigForm.id} onChange={(event) => setServerConfigForm({ ...serverConfigForm, id: event.target.value.toLowerCase() })} /></label><label>显示名称<input value={serverConfigForm.name} onChange={(event) => setServerConfigForm({ ...serverConfigForm, name: event.target.value })} /></label><label>适配器<select value={serverConfigForm.adapter} onChange={(event) => setServerConfigForm({ ...serverConfigForm, adapter: event.target.value })}><option value="bds-process">BDS 进程</option><option value="endstone-rcon">Endstone RCON（扩展）</option></select></label><label>服务器目录<input value={serverConfigForm.root} onChange={(event) => setServerConfigForm({ ...serverConfigForm, root: event.target.value })} placeholder="例如：D:\\Minecraft\\server" /></label><label>启动命令（每行一个参数）<textarea value={serverConfigForm.command} onChange={(event) => setServerConfigForm({ ...serverConfigForm, command: event.target.value })} /></label><label>日志相对路径<input value={serverConfigForm.log_path} onChange={(event) => setServerConfigForm({ ...serverConfigForm, log_path: event.target.value })} /></label><label>世界目录相对路径<input value={serverConfigForm.world_path} onChange={(event) => setServerConfigForm({ ...serverConfigForm, world_path: event.target.value })} /></label>{serverConfigForm.adapter === 'endstone-rcon' && <><label>RCON 地址<input value={serverConfigForm.rcon_host} onChange={(event) => setServerConfigForm({ ...serverConfigForm, rcon_host: event.target.value })} /></label><label>RCON 密码环境变量<input value={serverConfigForm.rcon_password_env} onChange={(event) => setServerConfigForm({ ...serverConfigForm, rcon_password_env: event.target.value.toUpperCase() })} /></label></>}<button>保存并注册</button></form>
            <p className="settings-note">已有配置：{serverConfigs.data?.map((config) => `${config.name} · ${config.adapter}`).join('、') || '只有演示服务器'}</p>
          </article>
          <article className="panel settings-card"><div className="panel-heading"><div><p className="eyebrow">TOOL POLICY</p><h2>工具执行策略</h2></div><span className="tag warning">逐项控制</span></div><div className="policy-list">{policies.data?.map((policy) => <div className="policy-row" key={policy.tool_name}><span><strong>{policy.tool_name}</strong><small>{policy.risk}</small></span><select value={policy.mode} onChange={(event) => changePolicy(policy, event.target.value)}><option value="auto">自动</option><option value="confirm">审批</option><option value="disabled">禁用</option></select></div>)}</div></article>
          <article className="panel settings-card audit-card"><div className="panel-heading"><div><p className="eyebrow">BACKUP INVENTORY</p><h2>备份记录</h2></div><span className="tag">审批保护</span></div>{backups.data?.length ? backups.data.slice(0, 6).map((backup) => <div className="audit-row" key={backup.id}><span>{backup.verified ? '✓' : '未校验'} · {backup.id}</span><small>{new Date(backup.created_at).toLocaleString()} · {(backup.size_bytes / 1024).toFixed(1)} KB</small></div>) : <div className="empty-state compact">暂无备份；可在 Agent 对话中请求创建备份。</div>}</article>
          <article className="panel settings-card audit-card"><div className="panel-heading"><div><p className="eyebrow">AUDIT TRAIL</p><h2>最近审计记录</h2></div></div>{audits.data?.slice(0, 6).map((audit) => <div className="audit-row" key={audit.id}><span>{audit.action} · {audit.tool_name || 'agent'}</span><small>{new Date(audit.created_at).toLocaleString()}</small></div>)}</article>
        </section>
        <footer>ANL MineOps 是独立的社区项目，与 Mojang、Microsoft、Minecraft 官方没有隶属或背书关系。</footer>
      </main>
    </div>
  )
}

export default App

import { useEffect, useState } from 'react'
import { api, type ModelInfo } from './api'
import { AutoplayBanner } from './components/AutoplayBanner'
import { Dock } from './components/Dock'
import { Inspector } from './components/Inspector'
import { LeftPanel } from './components/LeftPanel'
import { OfficeCanvas } from './components/OfficeCanvas'
import { ProgressPage } from './components/ProgressPage'
import { Toasts } from './components/Toasts'
import { TopBar } from './components/TopBar'
import { useQ } from './useQ'

export default function App() {
  const q = useQ()
  const { model } = q
  const [selected, setSelected] = useState<string | null>(null)
  const [progressOpen, setProgressOpen] = useState(false)
  const agent = selected ? model.agents.get(selected) : undefined
  const [models, setModels] = useState<ModelInfo[]>([])
  useEffect(() => {
    if (q.backend === 'ok') api.models().then(setModels).catch(() => {})
  }, [q.backend])

  return (
    <div className="flex h-full flex-col">
      <TopBar
        title={model.goal}
        build={q.builds}
        percent={model.progress.percent}
        hasProject={!!q.projectId}
        active={model.activeCount}
        total={model.agents.size}
        mode={q.mode}
        onMode={q.setMode}
        demo={q.demo}
        recordings={q.recordings}
        onDemo={q.setDemo}
        speed={q.speed}
        onSpeed={q.setSpeed}
        metrics={model.metrics ?? (q.replay && q.metrics ? { ...q.metrics, loaded: undefined } : q.metrics)}
        appUrl={model.appUrl}
        cost={model.cost}
        connected={q.connected}
        done={model.finished ? model.finished.ok : null}
        session={model.scenario}
      />
      {model.autoplay && <AutoplayBanner auto={model.autoplay} replay={q.replay} onStop={() => void q.stopAutoplay()} onSpeed={(s) => void q.setAutoplaySpeed(s)} />}
      <div className="flex min-h-0 flex-1">
        <LeftPanel
          model={model}
          busy={q.busy}
          demo={q.demo}
          hasProject={!!q.projectId}
          recordings={q.recordings}
          recording={q.recording}
          onRecording={q.setRecording}
          config={q.config}
          preset={q.preset}
          onPreset={q.setPreset}
          fast={q.fast}
          onFast={q.setFast}
          onStart={q.start}
          onImport={q.startImport}
          mode={q.mode}
          replay={q.replay}
          projectId={q.projectId}
          humanRoles={q.humanRoles}
          onHumanRoles={q.setHumanRoles}
          onSubmit={q.submitTask}
          onCopyPath={q.copyPath}
          scenarios={q.scenarios}
          onScenario={q.startScenario}
          onWatch={q.startAutoplay}
          onProgress={() => setProgressOpen(true)}
        />
        <main className="relative min-w-0 flex-1 overflow-hidden" style={{ background: 'radial-gradient(ellipse at center, #141a2c 0%, #0b0d12 75%)' }}>
          <OfficeCanvas model={model} selected={selected} tempo={q.demo ? q.speed : 1} onSelect={setSelected} />
          {q.backend === 'down' && (
            <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-lg border border-[var(--warn)] bg-[#2a210a] px-4 py-2 text-[14px] text-[var(--warn)]">
              Waiting for the Q backend on port 8000…
            </div>
          )}
          <Toasts toasts={q.toasts} onDismiss={q.dismissToast} onDecide={q.decide} onEscalate={q.escalate} />
        </main>
        {agent && <Inspector agent={agent} model={model} projectId={q.projectId} replay={q.replay} models={models} onClose={() => setSelected(null)} onError={q.fail} onEscalate={q.escalate} />}
      </div>
      {progressOpen && <ProgressPage onClose={() => setProgressOpen(false)} onStart={q.startScenario} busy={q.busy} onError={q.fail} />}
      <Dock model={model} projectId={q.projectId} replay={q.replay} onDecide={q.decide} ticker={model.ticker} onSubmit={q.submitTask} onError={q.fail} onPost={q.postChannel} onTryAgain={q.startScenario} busy={q.busy} />
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api, type ModelInfo } from './api'
import { Dock } from './components/Dock'
import { Inspector } from './components/Inspector'
import { LeftPanel } from './components/LeftPanel'
import { OfficeCanvas } from './components/OfficeCanvas'
import { Toasts } from './components/Toasts'
import { TopBar } from './components/TopBar'
import { useQ } from './useQ'

export default function App() {
  const q = useQ()
  const { model } = q
  const [selected, setSelected] = useState<string | null>(null)
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
        onDemo={q.setDemo}
        speed={q.speed}
        onSpeed={q.setSpeed}
        metrics={q.metrics}
        appUrl={model.appUrl}
        connected={q.connected}
        done={model.finished ? model.finished.ok : null}
      />
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
          onStart={q.start}
        />
        <main className="relative min-w-0 flex-1 overflow-hidden" style={{ background: 'radial-gradient(ellipse at center, #141a2c 0%, #0b0d12 75%)' }}>
          <OfficeCanvas model={model} selected={selected} tempo={q.demo ? q.speed : 1} onSelect={setSelected} />
          {q.backend === 'down' && (
            <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-lg border border-[var(--warn)] bg-[#2a210a] px-4 py-2 text-[14px] text-[var(--warn)]">
              Waiting for the Q backend on port 8000…
            </div>
          )}
          <Toasts toasts={q.toasts} onDismiss={q.dismissToast} />
        </main>
        {agent && <Inspector agent={agent} model={model} projectId={q.projectId} replay={q.replay} models={models} onClose={() => setSelected(null)} onError={q.fail} />}
      </div>
      <Dock model={model} projectId={q.projectId} replay={q.replay} onDecide={q.decide} ticker={model.ticker} />
    </div>
  )
}

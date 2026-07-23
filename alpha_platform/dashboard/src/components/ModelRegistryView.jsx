import React from 'react';
import { Database, Binary, CheckCircle2, Award } from 'lucide-react';

export default function ModelRegistryView({ models }) {
  if (!models) return null;

  return (
    <div className="glass-panel rounded-2xl p-6 mb-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-indigo-950 border border-indigo-800 flex items-center justify-center text-indigo-400">
            <Database className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">AI Meta-Labeling Governance & Model Registry</h2>
            <p className="text-xs text-slate-400">Triple Barrier • Purged TimeSeries CV • Probability Calibration • Brier Quality Score</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {models.map((model) => (
          <div key={model.model_id} className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 font-mono text-xs">
            <div className="flex items-center justify-between mb-2">
              <span className="font-sans font-bold text-slate-100">{model.model_id}</span>
              <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800">
                {model.stage}
              </span>
            </div>

            <div className="text-[11px] text-slate-400 mb-3 truncate">
              Dataset Hash: <span className="text-slate-300">{model.dataset_hash.slice(0, 16)}...</span>
            </div>

            <div className="grid grid-cols-3 gap-2 p-2.5 rounded-lg bg-slate-950/80 border border-slate-850 mb-3 text-center">
              <div>
                <span className="text-[10px] text-slate-500 block">Brier Score</span>
                <span className="text-cyan-400 font-bold">{model.brier_score}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 block">PBO Score</span>
                <span className="text-emerald-400 font-bold">{model.pbo_score}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 block">DSR Score</span>
                <span className="text-emerald-400 font-bold">{model.dsr_score}</span>
              </div>
            </div>

            <div className="text-[11px] text-slate-400">
              Features ({model.features.length}): <span className="text-slate-300">{model.features.join(', ')}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

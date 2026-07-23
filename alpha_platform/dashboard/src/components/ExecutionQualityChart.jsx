import React from 'react';
import { Gauge, Clock, ShieldCheck } from 'lucide-react';

export default function ExecutionQualityChart() {
  return (
    <div className="glass-panel rounded-2xl p-6 mb-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="h-8 w-8 rounded-lg bg-emerald-950 border border-emerald-800 flex items-center justify-center text-emerald-400">
          <Gauge className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Exness MT5 Execution Quality Analytics</h2>
          <p className="text-xs text-slate-400">Real-time Fill vs Expected Price • Slippage & Latency Tracking</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 font-mono text-xs">
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center gap-4">
          <div className="h-10 w-10 rounded-xl bg-emerald-950/80 border border-emerald-800 flex items-center justify-center text-emerald-400 text-lg font-extrabold">
            98
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Broker Quality Score</span>
            <span className="text-emerald-400 font-bold text-sm">EXCELLENT (Exness)</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center gap-4">
          <div className="h-10 w-10 rounded-xl bg-cyan-950/80 border border-cyan-800 flex items-center justify-center text-cyan-400">
            <Clock className="h-5 w-5" />
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Avg Execution Latency</span>
            <span className="text-slate-100 font-bold text-sm">42 ms</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center gap-4">
          <div className="h-10 w-10 rounded-xl bg-indigo-950/80 border border-indigo-800 flex items-center justify-center text-indigo-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Average Slippage</span>
            <span className="text-indigo-300 font-bold text-sm">+0.12 pips</span>
          </div>
        </div>
      </div>
    </div>
  );
}

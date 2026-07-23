import React from 'react';
import { ShieldCheck, Activity, Radio, AlertTriangle, Send } from 'lucide-react';

export default function Header({ systemStatus, emergencyKillActive }) {
  return (
    <header className="glass-panel sticky top-0 z-50 px-6 py-4 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <ShieldCheck className="h-6 w-6 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            ALPHA QUANT <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800 font-mono">v1.2.0</span>
          </h1>
          <p className="text-xs text-slate-400">Institutional Quantitative Research & Exness MT5 Execution</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* MT5 Connection Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-400 text-xs font-medium">
          <Radio className="h-3.5 w-3.5 animate-pulse" />
          <span>Exness MT5: CONNECTED</span>
        </div>

        {/* Rust Risk Engine Authority Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-950/60 border border-indigo-800 text-indigo-300 text-xs font-medium">
          <Activity className="h-3.5 w-3.5 text-indigo-400" />
          <span>Rust Risk Core: ACTIVE</span>
        </div>

        {/* Emergency Kill State */}
        {emergencyKillActive ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-950/80 border border-rose-700 text-rose-300 text-xs font-bold animate-bounce">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>KILL SWITCH ACTIVE</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-750 text-slate-300 text-xs font-medium">
            <ShieldCheck className="h-3.5 w-3.5 text-cyan-400" />
            <span>Risk Guard: ARMED</span>
          </div>
        )}

        {/* Telegram Alert Badge */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-950/50 border border-sky-800 text-sky-400 text-xs font-medium">
          <Send className="h-3.5 w-3.5" />
          <span>Telegram Alerts</span>
        </div>
      </div>
    </header>
  );
}

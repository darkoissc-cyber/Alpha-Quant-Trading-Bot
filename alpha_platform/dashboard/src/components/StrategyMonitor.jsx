import React from 'react';
import { Cpu, CheckCircle2, AlertOctagon, Layers } from 'lucide-react';

export default function StrategyMonitor({ strategies }) {
  if (!strategies) return null;

  return (
    <div className="glass-panel rounded-2xl p-6 mb-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-cyan-950 border border-cyan-800 flex items-center justify-center text-cyan-400">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Alpha Strategy Generators & Gate Monitor</h2>
            <p className="text-xs text-slate-400">Generates Trade Candidates • Filtered by AI Meta-Labeler • Gated by PBO & DSR</p>
          </div>
        </div>
        <span className="text-xs font-mono bg-slate-900 border border-slate-800 text-slate-300 px-3 py-1 rounded-full">
          Total Strategies: {strategies.length}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-900/80 text-slate-400 font-semibold border-b border-slate-800 uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3">Strategy ID / Name</th>
              <th className="px-4 py-3">Symbol</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3">Win Rate</th>
              <th className="px-4 py-3">Sharpe</th>
              <th className="px-4 py-3">PBO (&lt;0.10)</th>
              <th className="px-4 py-3">DSR (&gt;1.5)</th>
              <th className="px-4 py-3 text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {strategies.map((strat) => {
              const pboPassed = strat.pbo < 0.10;
              const dsrPassed = strat.dsr > 1.5;

              return (
                <tr key={strat.id} className="hover:bg-slate-900/40 transition-colors">
                  <td className="px-4 py-3.5 font-sans font-medium text-white">
                    <div>{strat.name}</div>
                    <div className="text-xs font-mono text-slate-400">{strat.id}</div>
                  </td>
                  <td className="px-4 py-3.5 text-cyan-400 font-semibold">{strat.symbol}</td>
                  <td className="px-4 py-3.5 font-sans text-slate-300">{strat.type}</td>
                  <td className="px-4 py-3.5">
                    <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-950 text-indigo-300 border border-indigo-800">
                      {strat.stage}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-slate-100 font-semibold">{(strat.win_rate * 100).toFixed(0)}%</td>
                  <td className="px-4 py-3.5 text-emerald-400 font-semibold">{strat.sharpe_ratio.toFixed(2)}</td>
                  
                  {/* PBO Check */}
                  <td className="px-4 py-3.5">
                    <span className={`flex items-center gap-1 font-semibold ${pboPassed ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {pboPassed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertOctagon className="h-3.5 w-3.5" />}
                      {strat.pbo.toFixed(2)}
                    </span>
                  </td>

                  {/* DSR Check */}
                  <td className="px-4 py-3.5">
                    <span className={`flex items-center gap-1 font-semibold ${dsrPassed ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {dsrPassed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertOctagon className="h-3.5 w-3.5" />}
                      {strat.dsr.toFixed(2)}
                    </span>
                  </td>

                  <td className="px-4 py-3.5 text-right font-sans">
                    <span className={`px-2.5 py-1 rounded-full text-[11px] font-bold ${
                      strat.status === 'ACTIVE'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                        : strat.status === 'PAPER_TRADING'
                        ? 'bg-amber-950 text-amber-400 border border-amber-800'
                        : 'bg-slate-900 text-slate-400 border border-slate-800'
                    }`}>
                      {strat.status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

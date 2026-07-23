import React from 'react';
import { DollarSign, TrendingUp, AlertCircle, PieChart } from 'lucide-react';

export default function PortfolioOverview({ portfolio }) {
  if (!portfolio) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 mb-6">
      {/* Total Equity Card */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-cyan-500/40 transition-all">
        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <DollarSign className="h-16 w-16 text-cyan-400" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Total Equity</p>
        <h3 className="text-2xl font-extrabold text-white font-mono tracking-tight">
          ${portfolio.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </h3>
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <span>Balance: <span className="font-mono text-slate-200">${portfolio.balance.toLocaleString()}</span></span>
          <span className="text-cyan-400 font-mono">Peak: ${portfolio.peak_equity.toLocaleString()}</span>
        </div>
      </div>

      {/* Daily PnL Card */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-emerald-500/40 transition-all">
        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <TrendingUp className="h-16 w-16 text-emerald-400" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Daily Performance</p>
        <h3 className="text-2xl font-extrabold text-emerald-400 font-mono tracking-tight">
          +${portfolio.daily_pnl.toFixed(2)} <span className="text-sm font-semibold">({portfolio.daily_pnl_pct}%)</span>
        </h3>
        <p className="mt-2 text-xs text-slate-400">Target Volatility: <span className="text-emerald-400 font-mono">10.0% p.a.</span></p>
      </div>

      {/* Current Drawdown vs Limits */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-amber-500/40 transition-all">
        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <AlertCircle className="h-16 w-16 text-amber-400" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Current Drawdown</p>
        <h3 className="text-2xl font-extrabold text-slate-100 font-mono tracking-tight">
          {portfolio.current_drawdown_pct}%
        </h3>
        <div className="mt-2 text-xs space-y-1">
          <div className="flex justify-between text-slate-400">
            <span>Soft Limit (Auto De-risk):</span>
            <span className="font-mono text-amber-400">{portfolio.soft_limit_pct}%</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Hard Limit (Kill Switch):</span>
            <span className="font-mono text-rose-400">{portfolio.hard_limit_pct}%</span>
          </div>
        </div>
      </div>

      {/* Exposure Allocation (HRP) */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden group hover:border-indigo-500/40 transition-all">
        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <PieChart className="h-16 w-16 text-indigo-400" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">HRP Exposure</p>
        <div className="grid grid-cols-2 gap-2 mt-2 font-mono text-xs">
          {Object.entries(portfolio.exposure).map(([asset, exp]) => (
            <div key={asset} className="flex items-center justify-between px-2 py-1 rounded bg-slate-900/80 border border-slate-800">
              <span className="text-slate-300 font-semibold">{asset}</span>
              <span className="text-indigo-400">{(exp * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

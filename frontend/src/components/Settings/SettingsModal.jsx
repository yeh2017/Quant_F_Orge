import React, { useState, useEffect, useCallback } from 'react';
import { X, Eye, EyeOff, Save, TestTube, Database, Bot, Bell, Activity, ExternalLink, Gauge, Shield, Clock, Server, Send, CheckCircle, XCircle } from 'lucide-react';
import { systemApi, newsApi } from '../../services/api';

function SecretInput({ value, onChange, placeholder }) {
    const [visible, setVisible] = useState(false);
    const isMasked = value && value.includes('****');
    return (
        <div className="relative">
            <input type={visible ? 'text' : 'password'} value={value} onChange={onChange} placeholder={placeholder}
                className="w-full px-3 py-2 text-sm bg-gray-50 text-gray-800 rounded-lg border border-gray-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 pr-8" />
            <button type="button" onClick={() => setVisible(!visible)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
            {isMasked && <span className="text-xs text-gray-500 mt-0.5 block">留空不改 · 输入新值覆盖</span>}
        </div>
    );
}

function NumField({ label, hint, value, onChange, placeholder, unit }) {
    return (
        <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 w-28 shrink-0">{label}</label>
            <input type="text" value={value} onChange={onChange} placeholder={placeholder}
                className="w-20 px-2 py-1 text-xs bg-gray-50 text-gray-800 rounded border border-gray-300 focus:outline-none focus:border-indigo-500 text-center font-mono" />
            {unit && <span className="text-xs text-gray-600 shrink-0">{unit}</span>}
            <span className="text-xs text-gray-500 truncate">{hint}</span>
        </div>
    );
}

// 渠道配置定义
const CHANNEL_DEFS = [
    { key: 'pushplus', label: 'PushPlus', icon: '📱', desc: '微信公众号推送', link: 'https://www.pushplus.plus', linkText: 'pushplus.plus',
      fields: [{ name: 'token', label: 'Token', secret: true, placeholder: '注册后 → 功能 → 一对一推送 → 复制 Token' },
               { name: 'topic', label: '群组编码', secret: false, placeholder: '选填，一对多推送时填写' }] },
    { key: 'serverchan', label: 'Server酱', icon: '📢', desc: '手机APP推送', link: 'https://sct.ftqq.com', linkText: 'sct.ftqq.com',
      fields: [{ name: 'sendkey', label: 'SendKey', secret: true, placeholder: '登录后 → Key & API → 复制 SendKey' }] },
    { key: 'feishu', label: '飞书', icon: '📨', desc: '飞书群机器人', link: 'https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot', linkText: '飞书文档',
      fields: [{ name: 'webhook', label: 'Webhook URL', secret: false, placeholder: 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx' }] },
    { key: 'telegram', label: 'Telegram', icon: '✈️', desc: '国内需代理', link: 'https://core.telegram.org/bots#botfather', linkText: '@BotFather',
      fields: [{ name: 'bot_token', label: 'Bot Token', secret: true, placeholder: 'BotFather 获取' },
               { name: 'chat_id', label: 'Chat ID', secret: true, placeholder: '@userinfobot 获取' },
               { name: 'proxy', label: '代理地址', secret: false, placeholder: 'http://127.0.0.1:10808（选填）' }] },
    { key: 'wechat', label: '企业微信', icon: '💬', desc: '企业微信群机器人',
      fields: [{ name: 'webhook_url', label: 'Webhook URL', secret: false, placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx' }] },
    { key: 'webhook', label: '自定义Webhook', icon: '🔗', desc: '支持钉钉（自动识别URL）',
      fields: [{ name: 'url', label: 'URL', secret: false, placeholder: 'https://oapi.dingtalk.com/robot/send?access_token=xxx' }] },
];

const NAV_ITEMS = [
    { key: 'general', label: '全局设置', icon: '⚙️' },
    { key: 'push_strategy', label: '推送策略', icon: '📢' },
    ...CHANNEL_DEFS.map(c => ({ key: c.key, label: c.label, icon: c.icon })),
];


export default function SettingsModal({ onClose }) {
    const [config, setConfig] = useState(null);
    const [status, setStatus] = useState(null);
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [activeNav, setActiveNav] = useState('general');
    const [testingChannel, setTestingChannel] = useState('');

    const loadConfig = useCallback(async () => {
        try {
            const [cfg, st] = await Promise.all([systemApi.getConfig(), systemApi.getStatus()]);
            setConfig(cfg); setStatus(st);
        } catch (e) { setMsg('❌ 加载配置失败: ' + e.message); }
    }, []);

    useEffect(() => { loadConfig(); }, [loadConfig]);

    const updateEnv = (key, value) => setConfig(prev => ({ ...prev, env: { ...prev.env, [key]: value } }));
    const updateChannel = (channel, field, value) => setConfig(prev => ({
        ...prev, notify: { ...prev.notify, [channel]: { ...prev.notify[channel], [field]: value } },
    }));
    const updateNotifyField = (key, value) => setConfig(prev => ({ ...prev, notify: { ...prev.notify, [key]: value } }));

    const handleSave = async () => {
        setSaving(true); setMsg('');
        try {
            await systemApi.updateConfig(config);
            // 如果有已配置的 LLM 供应商，保存后自动验证连通性
            // 检查 env 中是否有任何 LLM Key（比 p.configured 更准确，因为用户可能刚填入）
            const hasLlmKey = (config.llm_providers || []).some(p => {
                const keyName = `LLM_${p.name.toUpperCase()}_KEY`;
                const val = env[keyName] || '';
                return val && !val.includes('****');  // 有值且不是脱敏占位符（用户未改）
            }) || (config.llm_providers || []).some(p => p.configured);
            if (hasLlmKey) {
                setMsg('✅ 配置已保存，正在验证 LLM 连通性...');
                try {
                    const llmResult = await systemApi.testLlm();
                    const details = (llmResult.results || [])
                        .map(r => {
                            const icon = r.status === 'ok' ? '✅' : r.status === 'no_balance' ? '⚠️' : '❌';
                            return `${icon} ${r.name}: ${r.detail}`;
                        })
                        .join('  ·  ');
                    setMsg(`✅ 已保存 · ${details}`);
                } catch { setMsg('✅ 配置已保存（LLM 验证超时）'); }
            } else {
                setMsg('✅ 配置已保存');
            }
            setTimeout(() => setMsg(''), 8000);
        }
        catch (e) { setMsg('❌ 保存失败: ' + e.message); }
        setSaving(false);
    };

    const handleTestChannel = async (channelKey) => {
        setTestingChannel(channelKey); setMsg('保存并测试中...');
        try {
            // 先保存当前配置，确保后端测试的是最新填写的值
            await systemApi.updateConfig(config);
            const res = await newsApi.testNotify(channelKey);
            setMsg(res?.detail || (res?.success ? '✅ 测试成功！' : '❌ 推送失败'));
        } catch (e) { setMsg('❌ ' + (e?.message || '请求失败')); }
        setTestingChannel('');
        setTimeout(() => setMsg(''), 6000);
    };

    if (!config) return null;
    const env = config.env || {};
    const notify = config.notify || {};

    const renderChannelPanel = (def) => {
        const ch = notify[def.key] || {};
        return (
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-base font-semibold text-gray-800 flex items-center gap-2">
                            <span>{def.icon}</span> {def.label}
                            <span className="text-xs text-gray-400 font-normal">{def.desc}</span>
                        </h3>
                    </div>
                    <label className="flex items-center gap-2 cursor-pointer">
                        <span className="text-xs text-gray-500">{ch.enabled ? '已启用' : '未启用'}</span>
                        <div className={`relative w-10 h-5 rounded-full transition-colors ${ch.enabled ? 'bg-indigo-500' : 'bg-gray-300'}`}
                            onClick={() => updateChannel(def.key, 'enabled', !ch.enabled)}>
                            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${ch.enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
                        </div>
                    </label>
                </div>
                {def.link && (
                    <a href={def.link} target="_blank" rel="noreferrer"
                        className="text-xs text-indigo-500 hover:text-indigo-600 inline-flex items-center gap-1">
                        {def.linkText} <ExternalLink className="w-3 h-3" />
                    </a>
                )}
                {ch.enabled && (
                    <div className="space-y-3">
                        {def.fields.map(f => (
                            <div key={f.name}>
                                <label className="text-xs text-gray-500 mb-1 block">{f.label}</label>
                                {f.secret ? (
                                    <SecretInput value={ch[f.name] || ''} onChange={e => updateChannel(def.key, f.name, e.target.value)} placeholder={f.placeholder} />
                                ) : (
                                    <input value={ch[f.name] || ''} onChange={e => updateChannel(def.key, f.name, e.target.value)} placeholder={f.placeholder}
                                        className="w-full px-3 py-2 text-sm bg-gray-50 text-gray-800 rounded-lg border border-gray-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30" />
                                )}
                            </div>
                        ))}
                        <button onClick={() => handleTestChannel(def.key)} disabled={testingChannel === def.key}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-50 text-indigo-600 rounded-lg hover:bg-indigo-100 disabled:opacity-50 transition-all border border-indigo-200">
                            <Send className="w-3.5 h-3.5" />
                            {testingChannel === def.key ? '发送中...' : '发送测试消息'}
                        </button>
                    </div>
                )}
            </div>
        );
    };


    const renderGeneralPanel = () => (
        <div className="space-y-6">
            {/* 数据源 */}
            <section>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                    <Database className="w-4 h-4 text-blue-500" /> 数据源
                </h3>
                <div className="space-y-3">
                    <div>
                        <label className="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
                            Tushare Token
                            <a href="https://tushare.pro/weborder/#/login?reg=624267" target="_blank" rel="noreferrer" className="text-indigo-500 hover:text-indigo-600 inline-flex items-center gap-0.5">
                                tushare.pro/weborder/#/login?reg=624267 <ExternalLink className="w-3 h-3" />
                            </a>
                        </label>
                        <SecretInput value={env.TUSHARE_TOKEN || ''} onChange={e => updateEnv('TUSHARE_TOKEN', e.target.value)} placeholder="注册后 → 个人中心 → 复制 Token" />
                    </div>
                    <div>
                        <label className="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
                            积分等级
                            <a href="https://tushare.pro/weborder/#/user/privilege" target="_blank" rel="noreferrer" className="text-indigo-500 hover:text-indigo-600 inline-flex items-center gap-0.5">
                                查看权限 <ExternalLink className="w-3 h-3" />
                            </a>
                        </label>
                        <div className="flex gap-2 mt-1">
                            {[
                                { pts: 120, label: '120 免费', desc: '日线/ETF/行业/基础财务' },
                                { pts: 2000, label: '2000 基础', desc: '+估值指标/指数权重/财报' },
                                { pts: 5000, label: '5000 进阶', desc: '+转债/资金流/融资/事件' },
                            ].map(({ pts, label, desc }) => {
                                const active = String(env.TUSHARE_POINTS || '2000') === String(pts);
                                return (
                                    <button key={pts} type="button"
                                        onClick={() => updateEnv('TUSHARE_POINTS', String(pts))}
                                        className={`flex-1 px-3 py-2.5 rounded-lg border text-sm font-medium transition-all flex flex-col items-center gap-0.5 ${
                                            active
                                                ? 'bg-indigo-100 border-indigo-400 text-indigo-700 ring-1 ring-indigo-300'
                                                : 'bg-gray-50 border-gray-200 text-gray-500 hover:border-gray-400'
                                        }`}>
                                        <span>{label}</span>
                                        <span className={`text-xs font-normal ${active ? 'text-indigo-500' : 'text-gray-400'}`}>{desc}</span>
                                    </button>
                                );
                            })}
                        </div>
                        <p className="text-xs text-gray-400 mt-1">影响数据中心可同步范围，积分不足的数据类型会自动跳过</p>
                    </div>
                    <div>
                        <label className="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
                            Tavily API Key <span className="text-gray-400">（选填，新闻搜索增强）</span>
                            <a href="https://app.tavily.com/home" target="_blank" rel="noreferrer" className="text-indigo-500 hover:text-indigo-600 inline-flex items-center gap-0.5">
                                tavily.com <ExternalLink className="w-3 h-3" />
                            </a>
                        </label>
                        <SecretInput value={env.TAVILY_API_KEY || ''} onChange={e => updateEnv('TAVILY_API_KEY', e.target.value)} placeholder="Dashboard → API Keys → 复制" />
                    </div>
                </div>
            </section>

            {/* AI 模型（多供应商） */}
            <section>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                    <Bot className="w-4 h-4 text-purple-500" /> AI 模型
                    <span className="text-xs text-gray-400 font-normal">多渠道自动降级</span>
                </h3>
                <div className="space-y-3">
                    {/* 供应商卡片 */}
                    <div className="space-y-2">
                        <label className="text-xs text-gray-500 block">供应商（按优先级排序，主挂了自动切备用）</label>
                        {(config.llm_providers || []).length > 0 ? (
                            (config.llm_providers || []).map((p, i) => {
                                const keyEnvName = `LLM_${p.name.toUpperCase()}_KEY`;
                                const modelEnvName = `LLM_${p.name.toUpperCase()}_MODEL`;
                                const providerLinks = { siliconflow: 'https://cloud.siliconflow.cn/i/pt7eccra', anspire: 'https://open.anspire.cn/?share_code=UE3OKRUE' };
                                const providerLabels = { siliconflow: 'cloud.siliconflow.cn/i/pt7eccra', anspire: 'open.anspire.cn/?share_code=UE3OKRUE' };
                                return (
                                    <div key={p.name} className="px-3 py-2 bg-gray-50 rounded-lg border border-gray-200 space-y-1.5">
                                        <div className="flex items-center gap-2 text-xs">
                                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${p.configured ? 'bg-emerald-400' : 'bg-gray-300'}`} />
                                            <span className="font-medium text-gray-700">{p.name}</span>
                                            {providerLinks[p.name] && <a href={providerLinks[p.name]} target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:text-indigo-600 inline-flex items-center gap-0.5">{providerLabels[p.name] || p.name} <ExternalLink className="w-3 h-3" /></a>}
                                            {i === 0 ? <span className="ml-auto text-purple-500 text-[10px]">主</span> : <span className="ml-auto text-gray-400 text-[10px]">备用</span>}
                                        </div>
                                        <div className="space-y-1.5">
                                            <SecretInput value={env[keyEnvName] || ''} onChange={e => updateEnv(keyEnvName, e.target.value)}
                                                placeholder="API Key" />
                                            <select value={env[modelEnvName] || p.model || ''} onChange={e => updateEnv(modelEnvName, e.target.value)}
                                                className="w-full px-3 py-2 text-sm bg-gray-50 text-gray-800 rounded-lg border border-gray-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 font-mono">
                                                {(p.models || []).map(m => (
                                                    <option key={m.name} value={m.name}>
                                                        {m.name.split('/').pop()}{m.free ? '（免费）' : ''}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                );
                            })
                        ) : (
                            <span className="text-xs text-amber-500">未配置 LLM 供应商，将使用关键词评分</span>
                        )}
                    </div>
                    {/* 批处理 */}
                    <div>
                        <label className="text-xs text-gray-500 mb-1 block">批处理条数 <span className="text-gray-400">每次 LLM 请求同时分析的新闻数量，越大越省调用次数但 prompt 越长</span></label>
                        <input type="number" min="1" max="50" value={env.ERNIE_BATCH_SIZE} onChange={e => updateEnv('ERNIE_BATCH_SIZE', e.target.value)}
                            className="w-20 px-3 py-1.5 text-sm bg-gray-50 text-gray-800 rounded-lg border border-gray-300 focus:outline-none focus:border-purple-500 font-mono" />
                    </div>
                    {/* 月预算 */}
                    <div>
                        <label className="text-xs text-gray-500 mb-1 block">AI 分析月预算 <span className="text-gray-400">超出后降级为关键词评分</span></label>
                        {(() => {
                            const llmStats = config.llm_stats || {};
                            const monthlyBudget = Number(env.LLM_MONTHLY_BUDGET);
                            const avgNews = config.avg_daily_llm_news || 0;
                            const primary = (config.llm_providers || [])[0];
                            const primaryPricing = primary ? (config.model_pricing || {})[primary.model] : null;
                            if (primaryPricing?.input === 0 && primaryPricing?.output === 0) {
                                return <span className="text-xs text-emerald-600">主供应商模型免费，无需设置预算</span>;
                            }
                            return (
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm text-gray-600">¥</span>
                                    <input type="number" min="1" max="500" value={monthlyBudget} onChange={e => updateEnv('LLM_MONTHLY_BUDGET', e.target.value)}
                                        className="w-14 px-1.5 py-0.5 text-sm bg-gray-50 text-gray-800 rounded border border-gray-300 focus:outline-none focus:border-purple-500 font-mono text-center" />
                                    <span className="text-xs text-gray-400">/月</span>
                                    {[{yuan: 8, label: '省钱'}, {yuan: 15, label: '推荐'}, {yuan: 30, label: '宽裕'}].map(t => (
                                        <button key={t.yuan} onClick={() => updateEnv('LLM_MONTHLY_BUDGET', String(t.yuan))}
                                            className={`px-1.5 py-0.5 text-xs rounded transition-all ${monthlyBudget === t.yuan
                                                ? 'bg-purple-100 text-purple-700 border border-purple-300' : 'bg-gray-100 text-gray-500 border border-gray-200 hover:border-gray-300'}`}>
                                            ¥{t.yuan} {t.label}
                                        </button>
                                    ))}
                                    <span className="text-xs text-gray-500">
                                        {llmStats.calls > 0 ? `今日 ¥${(llmStats.cost_today || 0).toFixed(2)} · ${llmStats.calls}次` : `日预算 ¥${(monthlyBudget / 30).toFixed(2)}`}
                                        {avgNews > 0 && <span className="cursor-help" title="近7天日均需 LLM 评分的新闻数"> · {avgNews}条/日</span>}
                                    </span>
                                </div>
                            );
                        })()}
                    </div>
                </div>
            </section>

            {/* 数据保留 */}
            <section>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                    <Clock className="w-4 h-4 text-cyan-500" /> 数据保留 <span className="text-xs text-gray-400 font-normal">修改后需重启</span>
                </h3>
                <div className="space-y-2">
                    <NumField label="新闻保留" value={env.NEWS_RETAIN_DAYS} onChange={e => updateEnv('NEWS_RETAIN_DAYS', e.target.value)} unit="天" hint="覆盖一个季度" />
                    <NumField label="回测结果保留" value={env.BACKTEST_RESULT_RETAIN_DAYS} onChange={e => updateEnv('BACKTEST_RESULT_RETAIN_DAYS', e.target.value)} unit="天" hint="过期自动清理" />
                    <NumField label="历史数据保留" value={env.DB_RETAIN_YEARS} onChange={e => updateEnv('DB_RETAIN_YEARS', e.target.value)} unit="年" hint="日线/财务等" />
                    <NumField label="缓存保留" value={env.CACHE_RETAIN_DAYS} onChange={e => updateEnv('CACHE_RETAIN_DAYS', e.target.value)} unit="天" hint="临时计算缓存" />
                    <NumField label="日志保留" value={env.LOG_RETAIN_DAYS} onChange={e => updateEnv('LOG_RETAIN_DAYS', e.target.value)} unit="天" hint="运行日志" />
                </div>
            </section>

            {/* 高级设置 */}
            <div>
                <button onClick={() => setShowAdvanced(!showAdvanced)} className="text-xs text-gray-400 hover:text-gray-600 transition-colors">
                    {showAdvanced ? '▼ 收起高级设置' : '▶ 高级设置（限速 / 并发 / 熔断 / 服务端口）'}
                </button>
            </div>
            {showAdvanced && (
                <>
                    <section>
                        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                            <Gauge className="w-4 h-4 text-orange-500" /> 数据限速 <span className="text-xs text-gray-400 font-normal">积分越高可调越小 · 修改后需重启</span>
                        </h3>
                        <div className="space-y-1.5">
                            <NumField label="日线行情" value={env.TUSHARE_FETCH_SLEEP} onChange={e => updateEnv('TUSHARE_FETCH_SLEEP', e.target.value)} unit="秒/次" hint="120分:0.8 | 2000分:0.3 | 5000分:0.15" />
                            <NumField label="可转债行情" value={env.BOND_FETCH_SLEEP} onChange={e => updateEnv('BOND_FETCH_SLEEP', e.target.value)} unit="秒/次" hint="2000分:0.3 | 5000分:0.1" />
                            <NumField label="财务指标" value={env.FINANCIAL_SLEEP} onChange={e => updateEnv('FINANCIAL_SLEEP', e.target.value)} unit="秒/次" hint="2000分:2.0 | 5000分:0.8" />
                            <NumField label="资金流向" value={env.MONEYFLOW_SLEEP} onChange={e => updateEnv('MONEYFLOW_SLEEP', e.target.value)} unit="秒/次" hint="2000分:0.5 | 5000分:0.2" />
                            <NumField label="行业成分" value={env.SW_INDUSTRY_SLEEP} onChange={e => updateEnv('SW_INDUSTRY_SLEEP', e.target.value)} unit="秒/次" hint="2000分:1.5 | 5000分:0.5" />
                            <NumField label="个股新闻" value={env.AKSHARE_NEWS_SLEEP} onChange={e => updateEnv('AKSHARE_NEWS_SLEEP', e.target.value)} unit="秒/次" hint="AkShare 无需积分" />

                        </div>
                    </section>
                    <section>
                        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                            <Server className="w-4 h-4 text-sky-500" /> 并发与服务
                        </h3>
                        <div className="space-y-1.5">
                            <NumField label="财务并发线程" value={env.FINANCIAL_WORKERS} onChange={e => updateEnv('FINANCIAL_WORKERS', e.target.value)} unit="个" hint="并发拉取" />
                            <NumField label="批量写入" value={env.WRITE_BATCH_SIZE} onChange={e => updateEnv('WRITE_BATCH_SIZE', e.target.value)} unit="条/批" hint="数据库批量插入" />
                            <NumField label="服务地址" value={env.API_HOST} onChange={e => updateEnv('API_HOST', e.target.value)} hint="修改后需重启" />
                            <NumField label="服务端口" value={env.API_PORT} onChange={e => updateEnv('API_PORT', e.target.value)} hint="修改后需重启" />
                        </div>
                    </section>
                    <section>
                        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-2">
                            <Shield className="w-4 h-4 text-red-500" /> 熔断保护 <span className="text-xs text-gray-400 font-normal">连续失败时暂停调用</span>
                        </h3>
                        <div className="space-y-1.5">
                            <NumField label="令牌桶上限" value={env.TUSHARE_RATE_LIMIT_PER_MIN} onChange={e => updateEnv('TUSHARE_RATE_LIMIT_PER_MIN', e.target.value)} unit="次/分" hint="官方: 120分50 | 2000分200 | 5000分500" />
                            <NumField label="熔断阈值" value={env.TUSHARE_BREAKER_FAIL_THRESHOLD} onChange={e => updateEnv('TUSHARE_BREAKER_FAIL_THRESHOLD', e.target.value)} unit="次" hint="连续失败触发" />
                            <NumField label="熔断冷却" value={env.TUSHARE_BREAKER_COOLDOWN} onChange={e => updateEnv('TUSHARE_BREAKER_COOLDOWN', e.target.value)} unit="秒" hint="等待恢复" />
                        </div>
                    </section>
                </>
            )}

            {/* 系统状态 */}
            {status && (
                <section>
                    <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                        <Activity className="w-4 h-4 text-emerald-500" /> 系统状态
                    </h3>
                    <div className="flex items-center gap-4 text-xs text-gray-500">
                        <span>数据库大小: <span className="text-gray-700 font-mono">{status.db_size_mb} MB</span></span>
                    </div>
                </section>
            )}
        </div>
    );

    const renderPushStrategyPanel = () => (
        <div className="space-y-6">
            <section>
                <h3 className="text-base font-semibold text-gray-800 flex items-center gap-2 mb-1">
                    📢 推送策略
                    <span className="text-xs text-gray-400 font-normal">控制何时推送、推送什么内容</span>
                </h3>
                <p className="text-xs text-gray-500 mb-4">以下设置对所有已启用的渠道生效。具体渠道的开关请在左侧各渠道面板中配置。</p>
            </section>
            <section>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                    <Bell className="w-4 h-4 text-amber-500" /> 精选推送
                </h3>
                <label className="flex items-center gap-2 cursor-pointer" title={notify.auto_push_enabled ? '抓取后自动推送高情绪新闻' : '精选推送已关闭'}>
                    <div className={`relative w-10 h-5 rounded-full transition-colors ${notify.auto_push_enabled ? 'bg-amber-500' : 'bg-gray-300'}`}
                        onClick={() => updateNotifyField('auto_push_enabled', !notify.auto_push_enabled)}>
                        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${notify.auto_push_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
                    </div>
                    <span className="text-sm text-gray-700">{notify.auto_push_enabled ? '已开启' : '未开启'}</span>
                </label>
                <p className="text-xs text-gray-400 mt-2">开启后，每次新闻抓取完成会自动推送情绪分最强的新闻到所有已启用渠道。</p>
                {notify.auto_push_enabled && (
                    <div className="mt-3 space-y-1.5 pl-1">
                        <NumField label="推送条数" value={notify.push_top_n ?? 5} onChange={e => updateNotifyField('push_top_n', parseInt(e.target.value) || 5)} unit="条" hint="1-20，情绪分最高的前N条" />
                        <NumField label="情绪阈值" value={notify.push_threshold ?? 0.5} onChange={e => updateNotifyField('push_threshold', parseFloat(e.target.value) || 0.5)} hint="0.1-1.0，|评分|≥此值才推" />
                        <NumField label="冷却间隔" value={notify.push_cooldown_minutes ?? 10} onChange={e => updateNotifyField('push_cooldown_minutes', parseInt(e.target.value) || 10)} unit="分钟" hint="防止事件/新闻连推" />
                    </div>
                )}
                {notify.last_push && (
                    <p className={`text-xs mt-2 ${notify.last_push.success ? 'text-emerald-600' : 'text-red-500'}`}>
                        {notify.last_push.success ? '✅' : '❌'} 上次推送：{notify.last_push.time}
                        {notify.last_push.count > 0 ? ` · ${notify.last_push.count}条` : ''}
                        {notify.last_push.msg ? ` · ${notify.last_push.msg}` : ''}
                    </p>
                )}
            </section>
            <section>
                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 mb-3">
                    <Clock className="w-4 h-4 text-cyan-500" /> 定时摘要
                </h3>
                <p className="text-xs text-gray-500 mb-2">选择每天哪些时间点自动发送新闻日报摘要。不选 = 关闭。</p>
                <div className="flex gap-1.5 flex-wrap">
                    {[9, 12, 15, 18, 21].map(h => {
                        const hours = notify.summary_push_hours || [];
                        const active = hours.includes(h);
                        return (
                            <button key={h} onClick={() => updateNotifyField('summary_push_hours', active ? hours.filter(x => x !== h) : [...hours, h].sort((a, b) => a - b))}
                                className={`px-3 py-1 text-sm rounded-lg transition-all ${active ? 'bg-amber-100 text-amber-700 border border-amber-300 font-medium' : 'bg-gray-100 text-gray-500 border border-gray-200 hover:border-gray-300'}`}>
                                {h}:00
                            </button>
                        );
                    })}
                </div>
                {(notify.summary_push_hours || []).length > 0 && (
                    <p className="text-xs text-gray-500 mt-2">
                        📅 每天 {(notify.summary_push_hours || []).map(h => `${h}:00`).join('、')} 自动推送
                    </p>
                )}
                {notify.last_summary && (
                    <p className={`text-xs mt-1 ${notify.last_summary.success ? 'text-emerald-600' : 'text-red-500'}`}>
                        {notify.last_summary.success ? '✅' : '❌'} 上次摘要：{notify.last_summary.time}
                    </p>
                )}
            </section>
        </div>
    );

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
            <div className="bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl w-full max-w-3xl h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50 shrink-0">
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">⚙️ 系统设置</h2>
                    <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors"><X className="w-5 h-5" /></button>
                </div>
                {/* Body: 双栏 */}
                <div className="flex flex-1 min-h-0">
                    {/* 左栏导航 */}
                    <div className="w-36 shrink-0 bg-slate-800/60 border-r border-slate-700/50 py-3 overflow-y-auto">
                        {NAV_ITEMS.map((item, i) => (
                            <React.Fragment key={item.key}>
                                {i === 1 && <div className="mx-3 mt-3 mb-1 pt-2 border-t border-slate-700/50"><span className="text-xs text-slate-400 font-medium">推送渠道</span></div>}
                                <button onClick={() => setActiveNav(item.key)}
                                    className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-all ${
                                        activeNav === item.key
                                            ? 'bg-slate-700/60 text-white border-l-2 border-indigo-400'
                                            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/30 border-l-2 border-transparent'
                                    }`}>
                                    <span>{item.icon}</span>
                                    <span className="truncate">{item.label}</span>
                                    {item.key !== 'general' && item.key !== 'push_strategy' && notify[item.key]?.enabled && (
                                        <CheckCircle className="w-3 h-3 text-emerald-400 shrink-0 ml-auto" />
                                    )}
                                </button>
                            </React.Fragment>
                        ))}
                    </div>
                    {/* 右栏内容（白底） */}
                    <div className="flex-1 bg-white overflow-y-auto p-6">
                        {activeNav === 'general' ? renderGeneralPanel()
                         : activeNav === 'push_strategy' ? renderPushStrategyPanel()
                         : (() => {
                            const def = CHANNEL_DEFS.find(c => c.key === activeNav);
                            return def ? renderChannelPanel(def) : renderGeneralPanel();
                        })()}
                    </div>
                </div>
                {/* Footer */}
                <div className="flex items-center justify-between px-6 py-3 border-t border-slate-700/50 bg-slate-900 shrink-0">
                    <button onClick={handleSave} disabled={saving}
                        className="flex items-center gap-1.5 px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-all font-medium">
                        <Save className="w-4 h-4" /> {saving ? '保存中...' : '保存配置'}
                    </button>
                    {msg && <span className="text-xs text-slate-300">{msg}</span>}
                </div>
            </div>
        </div>
    );
}

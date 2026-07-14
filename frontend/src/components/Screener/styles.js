// 颜色工具：根据 group color 生成 tailwind class
export const groupStyles = {
    blue:    { bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    text: 'text-blue-400',    activeBg: 'bg-blue-500/20',    hoverBg: 'hover:bg-blue-500/15' },
    emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', activeBg: 'bg-emerald-500/20', hoverBg: 'hover:bg-emerald-500/15' },
    pink:    { bg: 'bg-pink-500/10',    border: 'border-pink-500/30',    text: 'text-pink-400',    activeBg: 'bg-pink-500/20',    hoverBg: 'hover:bg-pink-500/15' },
    amber:   { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-400',   activeBg: 'bg-amber-500/20',   hoverBg: 'hover:bg-amber-500/15' },
    cyan:    { bg: 'bg-cyan-500/10',    border: 'border-cyan-500/30',    text: 'text-cyan-400',    activeBg: 'bg-cyan-500/20',    hoverBg: 'hover:bg-cyan-500/15' },
    orange:  { bg: 'bg-orange-500/10',  border: 'border-orange-500/30',  text: 'text-orange-400',  activeBg: 'bg-orange-500/20',  hoverBg: 'hover:bg-orange-500/15' },
    slate:   { bg: 'bg-slate-500/10',   border: 'border-slate-500/30',   text: 'text-slate-400',   activeBg: 'bg-slate-500/20',   hoverBg: 'hover:bg-slate-500/15' },
    rose:    { bg: 'bg-rose-500/10',    border: 'border-rose-500/30',    text: 'text-rose-400',    activeBg: 'bg-rose-500/20',    hoverBg: 'hover:bg-rose-500/15' },
    violet:  { bg: 'bg-violet-500/10',  border: 'border-violet-500/30',  text: 'text-violet-400',  activeBg: 'bg-violet-500/20',  hoverBg: 'hover:bg-violet-500/15' },
    sky:     { bg: 'bg-sky-500/10',     border: 'border-sky-500/30',     text: 'text-sky-400',     activeBg: 'bg-sky-500/20',     hoverBg: 'hover:bg-sky-500/15' },
    teal:    { bg: 'bg-teal-500/10',    border: 'border-teal-500/30',    text: 'text-teal-400',    activeBg: 'bg-teal-500/20',    hoverBg: 'hover:bg-teal-500/15' },
    lime:    { bg: 'bg-lime-500/10',    border: 'border-lime-500/30',    text: 'text-lime-400',    activeBg: 'bg-lime-500/20',    hoverBg: 'hover:bg-lime-500/15' },
};

// 申万行业 → 投资逻辑一级分类
export const INDUSTRY_GROUPS = [
    { id: 'tech', icon: '🖥️', label: '科技', color: 'blue',
      keywords: ['半导体','软件开发','IT设备','消费电子','通信设备','计算机设备','电子元件','光学光电子','通信服务','计算机应用','电子制造','游戏','互联网服务','数字媒体','元器件','电信运营','互联网','软件服务','电器仪表','影视音像'] },
    { id: 'pharma', icon: '💊', label: '医药健康', color: 'emerald',
      keywords: ['化学制药','生物制品','医疗器械','中药','医药商业','医疗服务','生物制药','中成药','医疗保健'] },
    { id: 'consumer', icon: '🛒', label: '大消费', color: 'pink',
      keywords: ['食品饮料','酿酒','家用电器','纺织服装','商业百货','旅游酒店','教育','美容护理','零售','家居用品','纺织制造','服装家纺','食品加工','饮料制造','白色家电','小家电','休闲服务','白酒','啤酒','红黄酒','软饮料','乳制品','食品','饲料','百货','超市连锁','电器连锁','商品城','商贸代理','其他商业','服饰','纺织','日用化工','酒店餐饮','旅游景点','旅游服务','文教休闲','出版业','广告包装'] },
    { id: 'finance', icon: '🏦', label: '金融地产', color: 'amber',
      keywords: ['银行','证券','保险','多元金融','房地产开发','房地产服务','房地产','全国地产','区域地产','房产服务','园区开发'] },
    { id: 'energy', icon: '⚡', label: '新能源/制造', color: 'cyan',
      keywords: ['电气设备','电池','新能源','汽车整车','汽车配件','汽车服务','机械设备','航空装备','船舶制造','电源设备','光伏设备','风电设备','储能','工业机械','专用设备','通用设备','专用机械','工程机械','机床制造','机械基件','农用机械','纺织机械','轻工机械','运输设备','摩托车','船舶','新型电力'] },
    { id: 'cycle', icon: '⛏️', label: '周期', color: 'orange',
      keywords: ['钢铁','有色金属','煤炭开采','石油开采','基础化学','化工','建筑材料','建筑装饰','采掘','石油化工','化学原料','化学制品','金属制品','水泥制造','玻璃制造','工程建设','装修装饰','园林工程','普钢','特种钢','钢加工','铝','铜','铅锌','黄金','小金属','焦炭加工','石油加工','石油贸易','化工原料','化工机械','化纤','农药化肥','塑料','橡胶','染料涂料','玻璃','水泥','陶瓷','其他建材','矿物制品','造纸','建筑工程'] },
    { id: 'infra', icon: '🚛', label: '交运/公用', color: 'violet',
      keywords: ['公路','铁路','路桥','港口','水运','空运','航空','机场','公共交通','仓储物流','水力发电','火力发电','供气供热','水务','环境保护'] },
    { id: 'agri', icon: '🌾', label: '农林牧渔', color: 'lime',
      keywords: ['种植业','渔业','林业','农业综合','批发业'] },
    { id: 'other', icon: '📦', label: '其他', color: 'slate', keywords: [] },
];
